"""Initial clinic booking schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("doctors", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("specialization", sa.String(120), nullable=False))
    op.create_table("patients", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("contact", sa.String(200), nullable=False, unique=True))
    op.create_table("working_hours", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False), sa.Column("day_of_week", sa.Integer(), nullable=False), sa.Column("start_time", sa.Time(), nullable=False), sa.Column("end_time", sa.Time(), nullable=False), sa.CheckConstraint("end_time > start_time", name="ck_hours_positive"))
    op.create_index("ix_working_hours_doctor_id", "working_hours", ["doctor_id"])
    op.create_table("appointments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctors.id"), nullable=False), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False), sa.Column("start_time", sa.DateTime(timezone=True), nullable=False), sa.Column("end_time", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(16), server_default="BOOKED", nullable=False), sa.Column("cancel_reason", sa.String(500)), sa.Column("cancelled_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.create_index("ix_patient_appointment_start", "appointments", ["patient_id", "start_time"])
    op.create_index("uniq_active_slot", "appointments", ["doctor_id", "start_time"], unique=True, postgresql_where=sa.text("status = 'BOOKED'"), sqlite_where=sa.text("status = 'BOOKED'"))

def downgrade():
    op.drop_table("appointments")
    op.drop_index("ix_working_hours_doctor_id", table_name="working_hours")
    op.drop_table("working_hours")
    op.drop_table("patients")
    op.drop_table("doctors")
