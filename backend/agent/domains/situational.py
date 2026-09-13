from __future__ import annotations
from datetime import datetime, timezone
TIME_LIMIT_SECONDS = 13
def evaluate_response(*, presented_at: datetime, submitted_at: datetime | None, selected_option_id: str | None, custom_text: str | None = None) -> dict:
    if submitted_at is None: return {"status":"timeout","counted":False,"reason":"no_submission"}
    elapsed=(submitted_at-presented_at).total_seconds(); counted=0 <= elapsed <= TIME_LIMIT_SECONDS and bool(selected_option_id)
    return {"status":"counted" if counted else ("timeout" if elapsed>TIME_LIMIT_SECONDS else "invalid"),"counted":counted,"elapsed_seconds":round(max(0.0,elapsed),3),"selected_option_id":selected_option_id if counted else None,"custom_text":custom_text if counted and selected_option_id=="opt_custom" else None,"presented_at":presented_at.astimezone(timezone.utc).isoformat(),"submitted_at":submitted_at.astimezone(timezone.utc).isoformat()}
