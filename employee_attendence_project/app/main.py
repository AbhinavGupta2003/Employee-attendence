from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="1.0.0",
    description="API for tracking employee attendance, manual corrections with audit trails, and MongoDB aggregations."
)

# MongoDB Connection Configuration (Async Motor)
MONGO_URI = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_URI)
db = client.attendance_db

# --- Pydantic Models ---

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.type = "string"

class PunchInRequest(BaseModel):
    employee_id: str

class PunchOutRequest(BaseModel):
    employee_id: str

class AttendanceCorrectionRequest(BaseModel):
    admin_id: str
    new_punch_in: Optional[datetime] = None
    new_punch_out: Optional[datetime] = None
    reason: str = Field(..., min_length=5, description="Mandatory reason for manual correction")

class AuditTrailEntry(BaseModel):
    modified_at: datetime
    admin_id: str
    reason: str
    previous_state: dict
    new_state: dict

# --- Endpoints: Punch-In & Punch-Out ---

@app.post("/attendance/punch-in", status_code=status.HTTP_201_CREATED)
async def punch_in(payload: PunchInRequest):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Check if employee exists
    employee = await db.employees.find_one({"employee_id": payload.employee_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Business Rule: Check for an active open shift today
    active_shift = await db.attendance_logs.find_one({
        "employee_id": payload.employee_id,
        "date": today_str,
        "punch_out": None
    })
    
    if active_shift:
        raise HTTPException(status_code=400, detail="Active punch-in already exists. Punch out first.")

    record = {
        "employee_id": payload.employee_id,
        "date": today_str,
        "punch_in": datetime.utcnow(),
        "punch_out": None,
        "status": "active",
        "audit_trail": []
    }
    
    result = await db.attendance_logs.insert_one(record)
    return {"message": "Punch-in successful", "record_id": str(result.inserted_id)}

@app.post("/attendance/punch-out")
async def punch_out(payload: PunchOutRequest):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Find active shift
    active_shift = await db.attendance_logs.find_one({
        "employee_id": payload.employee_id,
        "date": today_str,
        "punch_out": None
    })
    
    if not active_shift:
        raise HTTPException(status_code=404, detail="No active punch-in found for today")

    now = datetime.utcnow()
    punch_in_time = active_shift["punch_in"]
    
    # Calculate worked duration in hours
    duration_hours = (now - punch_in_time).total_seconds() / 3600.0

    await db.attendance_logs.update_one(
        {"_id": active_shift["_id"]},
        {
            "$set": {
                "punch_out": now,
                "duration_hours": round(duration_hours, 2),
                "status": "completed"
            }
        }
    )
    
    return {
        "message": "Punch-out successful",
        "employee_id": payload.employee_id,
        "duration_hours": round(duration_hours, 2)
    }

# --- Endpoint: Manual Corrections with Audit Trail ---

@app.put("/attendance/{record_id}/correct")
async def correct_attendance(record_id: str, payload: AttendanceCorrectionRequest):
    if not ObjectId.is_valid(record_id):
        raise HTTPException(status_code=400, detail="Invalid record ID format")

    record = await db.attendance_logs.find_one({"_id": ObjectId(record_id)})
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    previous_state = {
        "punch_in": record.get("punch_in"),
        "punch_out": record.get("punch_out"),
        "status": record.get("status")
    }

    update_data = {}
    new_state = previous_state.copy()

    if payload.new_punch_in:
        update_data["punch_in"] = payload.new_punch_in
        new_state["punch_in"] = payload.new_punch_in
    if payload.new_punch_out:
        update_data["punch_out"] = payload.new_punch_out
        new_state["punch_out"] = payload.new_punch_out

    # Recalculate duration if both times are available
    p_in = update_data.get("punch_in", record.get("punch_in"))
    p_out = update_data.get("punch_out", record.get("punch_out"))
    if p_in and p_out:
        duration = (p_out - p_in).total_seconds() / 3600.0
        update_data["duration_hours"] = round(duration, 2)
        new_state["duration_hours"] = round(duration, 2)

    update_data["status"] = "corrected"
    new_state["status"] = "corrected"

    audit_entry = {
        "modified_at": datetime.utcnow(),
        "admin_id": payload.admin_id,
        "reason": payload.reason,
        "previous_state": previous_state,
        "new_state": new_state
    }

    await db.attendance_logs.update_one(
        {"_id": ObjectId(record_id)},
        {
            "$set": update_data,
            "$push": {"audit_trail": audit_entry}
        }
    )

    return {"message": "Attendance record successfully corrected", "audit_entry": audit_entry}

# --- Analytics Endpoints (MongoDB Aggregation Pipelines) ---

@app.get("/analytics/summary")
async def get_attendance_summary():
    """
    Aggregation pipeline to calculate total hours worked and total shifts per employee.
    """
    pipeline = [
        {
            "$match": {"status": {"$in": ["completed", "corrected"]}}
        },
        {
            "$group": {
                "_id": "$employee_id",
                "total_shifts": {"$sum": 1},
                "total_hours_worked": {"$sum": "$duration_hours"},
                "average_shift_hours": {"$avg": "$duration_hours"}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "employee_id",
                "as": "employee_info"
            }
        },
        {
            "$unwind": {"path": "$employee_info", "preserveNullAndEmptyArrays": True}
        },
        {
            "$project": {
                "_id": 0,
                "employee_id": "$_id",
                "employee_name": "$employee_info.name",
                "department": "$employee_info.department",
                "total_shifts": 1,
                "total_hours_worked": {"$round": ["$total_hours_worked", 2]},
                "average_shift_hours": {"$round": ["$average_shift_hours", 2]}
            }
        },
        {
            "$sort": {"total_hours_worked": -1}
        }
    ]

    cursor = db.attendance_logs.aggregate(pipeline)
    results = await cursor.to_list(length=100)
    return results