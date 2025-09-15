from flask import Flask, render_template, flash, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import calendar
from datetime import datetime, date, timedelta
from sqlalchemy import func
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv

SYDNEY_TZ = ZoneInfo("Australia/Sydney")

# Load the .env file
load_dotenv()

# Get secret values
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fallbacksecret")
SECRET_REGISTRATION_CODE = os.getenv("REGISTRATION_CODE", "DEFAULTCODE")

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///steps.db"
db = SQLAlchemy(app)


# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(128))
    steps = db.relationship("Step", backref="user", lazy=True)


class Step(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    date = db.Column(db.String(10))  # YYYY-MM-DD
    steps = db.Column(db.Integer)


# --- Routes ---
@app.route("/")
def index():
    return redirect(url_for("leaderboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        reg_code = request.form.get("registration_code", "").strip()

        # Check if username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already taken. Please choose another one.", "danger")
            return redirect(url_for("register"))

        # Validate the registration code
        if reg_code != SECRET_REGISTRATION_CODE:
            flash(
                "Invalid registration code. Please contact the challenge organizer.",
                "danger",
            )
            return redirect(url_for("register"))

        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user = User.query.get(user_id)

    # --- Date setup ---
    today = datetime.now().date()
    september_start = datetime(today.year, 9, 1).date()
    september_end = datetime(today.year, 9, 30).date()

    # Week navigation logic
    week_start_str = request.args.get("week_start")
    if week_start_str:
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    else:
        # Default to current week's Monday, but not before Sept 1
        week_start = max(today - timedelta(days=today.weekday()), september_start)

    # Clamp week_start inside September
    if week_start < september_start:
        week_start = september_start
    elif week_start > september_end:
        week_start = september_end

    week_end = min(week_start + timedelta(days=6), september_end)

    # --- Query data for dashboard ---
    # 1. Today's steps
    today_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(Step.user_id == user_id, Step.date == today)
        .scalar()
        or 0
    )

    # 2. Week's steps
    week_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(Step.user_id == user_id, Step.date.between(week_start, week_end))
        .scalar()
        or 0
    )

    # 3. Month's steps
    month_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(
            Step.user_id == user_id, Step.date.between(september_start, september_end)
        )
        .scalar()
        or 0
    )

    # --- Progress percentages ---
    daily_percent = min(int((today_steps / 15000) * 100), 100)
    weekly_percent = min(int((week_steps / 105000) * 100), 100)
    monthly_percent = min(int((month_steps / 450000) * 100), 100)

    # --- Weekly data for chart ---
    labels = []
    chart_data = []
    current_day = week_start

    while current_day <= week_end:
        steps_for_day = (
            db.session.query(func.sum(Step.steps))
            .filter(Step.user_id == user_id, Step.date == current_day)
            .scalar()
            or 0
        )
        labels.append(current_day.strftime("%a %d"))
        chart_data.append(steps_for_day)
        current_day += timedelta(days=1)

    return render_template(
        "dashboard.html",
        username=user.username,
        today=today,
        week_start=week_start,
        week_end=week_end,
        september_start=september_start,
        september_end=september_end,
        timedelta=timedelta,
        today_steps=today_steps,
        daily_percent=daily_percent,
        week_steps=week_steps,
        weekly_percent=weekly_percent,
        month_steps=month_steps,
        monthly_percent=monthly_percent,
        labels=labels,
        last_7_days=chart_data,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(url_for("report"))
        return "Invalid login!"
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/report", methods=["GET", "POST"])
def report():
    if "user_id" not in session:
        return redirect(url_for("login"))

    today_sydney = datetime.now(SYDNEY_TZ).date()
    september_start = date(today_sydney.year, 9, 1)
    september_end = date(today_sydney.year, 9, 30)

    if request.method == "POST":
        try:
            step_count = int(request.form["steps"])
            report_date_str = request.form.get("date", today_sydney.isoformat())
            report_date = datetime.fromisoformat(report_date_str).date()

            # Validate date
            if report_date > today_sydney:
                return "Cannot report steps for the future.", 400
            if report_date < september_start or report_date > september_end:
                return "Can only report steps for September.", 400

            # Check if entry exists
            existing = Step.query.filter_by(
                user_id=session["user_id"], date=report_date.isoformat()
            ).first()

            if existing:
                existing.steps = step_count
            else:
                new_step = Step(
                    user_id=session["user_id"],
                    date=report_date.isoformat(),
                    steps=step_count,
                )
                db.session.add(new_step)

            db.session.commit()
            return redirect(url_for("dashboard"))

        except ValueError:
            return "Invalid number of steps", 400

    return render_template("report.html", today=today_sydney)


@app.route("/leaderboard")
def leaderboard():
    today = datetime.now(SYDNEY_TZ).date()  # Sydney date
    daily_goal = 15000
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    weekly_goal = daily_goal * 7
    monthly_goal = daily_goal * days_in_month

    month_prefix = today.strftime("%Y-%m")
    start_week = today - timedelta(days=6)

    users = User.query.all()
    leaderboard_data = []

    for u in users:
        # Daily
        today_steps = (
            db.session.query(func.sum(Step.steps))
            .filter(Step.user_id == u.id, Step.date == today.isoformat())
            .scalar()
            or 0
        )
        daily_percent = min(int(today_steps / daily_goal * 100), 100)

        # Weekly
        week_steps = (
            db.session.query(func.sum(Step.steps))
            .filter(Step.user_id == u.id)
            .filter(Step.date >= start_week.isoformat(), Step.date <= today.isoformat())
            .scalar()
            or 0
        )
        weekly_percent = min(int(week_steps / weekly_goal * 100), 100)

        # Monthly
        month_steps = (
            db.session.query(func.sum(Step.steps))
            .filter(Step.user_id == u.id, Step.date.like(f"{month_prefix}%"))
            .scalar()
            or 0
        )
        monthly_percent = min(int(month_steps / monthly_goal * 100), 100)

        leaderboard_data.append(
            (
                u.username,
                today_steps,
                daily_percent,
                week_steps,
                weekly_percent,
                month_steps,
                monthly_percent,
            )
        )

    leaderboard_data.sort(key=lambda x: x[5], reverse=True)

    if not leaderboard_data:
        leaderboard_data.append(("No users", 0, 0, 0, 0, 0, 0))

    return render_template(
        "leaderboard.html",
        leaderboard=leaderboard_data,
        month=today.strftime("%B"),
        year=today.year,
        today=today,
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000)
