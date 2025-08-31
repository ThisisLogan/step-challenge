from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import calendar
from datetime import datetime, date, timedelta
from sqlalchemy import func
from zoneinfo import ZoneInfo  # Python 3.9+

SYDNEY_TZ = ZoneInfo("Australia/Sydney")

app = Flask(__name__)
app.secret_key = "supersecret"  # ⚠️ change in production
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


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        if User.query.filter_by(username=username).first():
            return "Username already exists!"
        db.session.add(User(username=username, password_hash=password))
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today = datetime.now(SYDNEY_TZ).date()  # Sydney date
    daily_goal = 15000
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    weekly_goal = daily_goal * 7
    monthly_goal = daily_goal * days_in_month

    # Daily steps
    today_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(Step.user_id == user_id, Step.date == today.isoformat())
        .scalar()
        or 0
    )
    daily_percent = min(int(today_steps / daily_goal * 100), 100)

    # Weekly steps
    start_week = today - timedelta(days=6)
    week_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(Step.user_id == user_id)
        .filter(Step.date >= start_week.isoformat(), Step.date <= today.isoformat())
        .scalar()
        or 0
    )
    weekly_percent = min(int(week_steps / weekly_goal * 100), 100)

    # Monthly steps
    month_prefix = today.strftime("%Y-%m")
    month_steps = (
        db.session.query(func.sum(Step.steps))
        .filter(Step.user_id == user_id, Step.date.like(f"{month_prefix}%"))
        .scalar()
        or 0
    )
    monthly_percent = min(int(month_steps / monthly_goal * 100), 100)

    # Last 7 days for chart
    last_7_days = []
    labels = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        step_count = (
            db.session.query(func.sum(Step.steps))
            .filter(Step.user_id == user_id, Step.date == day.isoformat())
            .scalar()
            or 0
        )
        last_7_days.append(step_count)
        labels.append(day.strftime("%d-%b"))

    return render_template(
        "dashboard.html",
        username=session["username"],
        today_steps=today_steps,
        daily_percent=daily_percent,
        week_steps=week_steps,
        weekly_percent=weekly_percent,
        month_steps=month_steps,
        monthly_percent=monthly_percent,
        last_7_days=last_7_days,
        labels=labels,
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

    # GET request
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
