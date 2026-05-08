from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from enum import Enum


class ActivityType(str, Enum):
    run = "run"
    ride = "ride"
    swim = "swim"
    walk = "walk"
    hike = "hike"
    strength = "strength"
    yoga = "yoga"
    other = "other"


class TrainingSessionStatus(str, Enum):
    planned = "planned"
    completed = "completed"
    skipped = "skipped"
    modified = "modified"


# ── Meals ─────────────────────────────────────────────────────────────────────

class MealCreate(BaseModel):
    user_id: str
    meal_date: date
    meal_time: Optional[str] = None  # "breakfast", "lunch", "dinner", "snack"
    name: str
    calories: float
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    quantity_g: Optional[float] = None
    notes: Optional[str] = None
    source: str = "manual"  # "manual", "telegram_text", "telegram_photo", "telegram_voice"


class MealOut(MealCreate):
    id: str
    created_at: datetime


# ── Activities ────────────────────────────────────────────────────────────────

class ActivityCreate(BaseModel):
    user_id: str
    activity_date: date
    activity_type: ActivityType = ActivityType.other
    name: str
    duration_min: float
    distance_km: Optional[float] = None
    elevation_m: Optional[float] = None
    calories: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    strava_id: Optional[str] = None
    notes: Optional[str] = None
    source: str = "manual"


class ActivityOut(ActivityCreate):
    id: str
    created_at: datetime


# ── Daily Health ──────────────────────────────────────────────────────────────

class DailyHealthCreate(BaseModel):
    user_id: str
    health_date: date
    weight_kg: Optional[float] = None
    sleep_hours: Optional[float] = None
    steps: Optional[int] = None
    body_battery: Optional[int] = None
    hrv_ms: Optional[float] = None
    stress_score: Optional[int] = None
    resting_hr: Optional[int] = None
    total_calories_iphone: Optional[int] = None
    notes: Optional[str] = None


class DailyHealthOut(DailyHealthCreate):
    id: str
    created_at: datetime


# ── User Profile ──────────────────────────────────────────────────────────────

class UserProfileCreate(BaseModel):
    telegram_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    goal: Optional[str] = None  # "lose_weight", "maintain", "gain_muscle"
    daily_calorie_goal: int = 2400
    protein_goal_g: int = 150
    carbs_goal_g: int = 280
    fat_goal_g: int = 75
    strava_athlete_id: Optional[str] = None
    strava_access_token: Optional[str] = None
    strava_refresh_token: Optional[str] = None
    strava_token_expires_at: Optional[datetime] = None


class UserProfileOut(UserProfileCreate):
    id: str
    created_at: datetime


# ── Training Plan ─────────────────────────────────────────────────────────────

class TrainingPlanCreate(BaseModel):
    user_id: str
    name: str
    goal: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    weekly_sessions: int = 4
    is_active: bool = True


class TrainingPlanOut(TrainingPlanCreate):
    id: str
    created_at: datetime


class TrainingSessionCreate(BaseModel):
    plan_id: str
    user_id: str
    scheduled_date: date
    activity_type: ActivityType
    title: str
    description: str
    duration_target_min: int
    distance_target_km: Optional[float] = None
    intensity: str = "moderate"  # "easy", "moderate", "hard", "race"
    status: TrainingSessionStatus = TrainingSessionStatus.planned
    notes: Optional[str] = None


class TrainingSessionOut(TrainingSessionCreate):
    id: str
    created_at: datetime


# ── Dashboard aggregations ────────────────────────────────────────────────────

class DailySummary(BaseModel):
    date: date
    total_calories_in: float
    total_calories_out: float
    net_calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    weight_kg: Optional[float]
    steps: Optional[int]
    sleep_hours: Optional[float]
    activities: list


class PlanAdjustmentRequest(BaseModel):
    reason: str  # "illness", "travel", "work", "injury", "other"
    detail: Optional[str] = None
    skip_days: Optional[int] = None
    reduce_intensity: Optional[bool] = False
