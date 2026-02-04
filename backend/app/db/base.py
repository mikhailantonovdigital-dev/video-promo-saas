from __future__ import annotations
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# noqa: F401
from app.models.user import User
from app.models.style import Style
from app.models.plan import Plan
from app.models.order import Order
from app.models.payment import Payment
