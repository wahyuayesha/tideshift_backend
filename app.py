from flask import Flask, g, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc
from firebase_config import *
from auth_decorator import firebase_required
from datetime import date, timedelta, datetime
import os
from dotenv import load_dotenv
from models import DailyGoalsLog, db, User, DailyCarbonLog
from carbon import (
    EMISSION_FACTORS,
    CATEGORY_MAPPING,
    calculate_carbon_emissions,
    classify_level,
    get_emission_category,
    CarbonFuzzySystem,
    generate_improvement_suggestions
)
import pymysql

# Setup MySQL driver
pymysql.install_as_MySQLdb()

# Load environment variables from .env (for local dev)
load_dotenv()

app = Flask(__name__)

# Read credentials from environment
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
SSL_PATH = os.environ.get("SSL_PATH")

# Configure SQLAlchemy with secure credentials
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?charset=utf8mb4&ssl_ca={SSL_PATH}"
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

with app.app_context():
    db.create_all()

# ============================
# ROUTE: Sync User
# ============================
@app.route('/me', methods=['POST'])
@firebase_required
def sync_user():
    from firebase_admin import auth as fb_auth
    try:
        decoded = fb_auth.get_user(request.user_uid)
        email = decoded.email
        created_at = datetime.fromtimestamp(decoded.user_metadata.creation_timestamp / 1000.0)
    except Exception as e:
        return jsonify({"message": "Failed to retrieve user from Firebase", "error": str(e)}), 500

    data = request.get_json() or {}
    username = data.get('username') or email.split("@")[0]
    profile_url = data.get('profilePicture') or "assets/images/profilePictures/default.png"

    user = User.query.filter_by(firebase_uid=request.user_uid).first()
    if not user:
        user = User(
            firebase_uid=request.user_uid,
            email=email,
            username=username,
            profilePicture=profile_url,
            joinDate=created_at,
            points=0,
            currentIslandTheme=0
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "New user saved to database"}), 201

    return jsonify({"message": "User already exists in database"}), 200

# ============================
# ROUTE: Get Profile
# ============================
@app.route('/me', methods=['GET'])
@firebase_required
def get_profile():
    user = User.query.filter_by(firebase_uid=request.user_uid).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    return jsonify({
        "email": user.email,
        "username": user.username,
        "profilePicture": user.profilePicture,
        "joinDate": user.joinDate.isoformat(),
        "points": user.points,
        "currentIslandTheme": user.currentIslandTheme,
        "firebase_uid": user.firebase_uid
    }), 200

# ============================
# ROUTE: Update Profile Picture
# ============================
@app.route('/me/profile-picture', methods=['PATCH'])
@firebase_required
def update_profile_picture():
    data = request.get_json() or {}
    new_url = data.get('profilePicture')
    if not new_url:
        return jsonify({'message': 'No profilePicture URL provided'}), 400

    user = User.query.filter_by(firebase_uid=request.user_uid).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    user.profilePicture = new_url
    db.session.commit()

    return jsonify({'message': 'Profile picture updated'}), 200

# ============================
# ROUTE: Update Current Island Theme
# ============================
@app.route('/me/current-island-theme', methods=['PATCH'])
@firebase_required
def update_current_island_theme():
    data = request.get_json() or {}
    if 'currentIslandTheme' not in data:
        return jsonify({'message': 'No currentIslandTheme provided'}), 400
    
    new_theme = data['currentIslandTheme']

    user = User.query.filter_by(firebase_uid=request.user_uid).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    user.currentIslandTheme = new_theme
    db.session.commit()

    return jsonify({
        'message': 'Current island theme updated successfully',
        'currentIslandTheme': user.currentIslandTheme
    }), 200


# ============================
# ROUTE: Leaderboard
# ============================
@app.route('/leaderboard', methods=['GET'])
@firebase_required
def leaderboard():
    # ambil 15 besar user berdasarkan points
    top_users = (
        db.session.query(User)
        .order_by(desc(User.points))
        .limit(15)
        .all()
    )

    leaderboard = [
        {
            "username": u.username,
            "points": int(u.points or 0),
            "profilePicture": u.profilePicture
        }
        for u in top_users
    ]

    # ambil user login berdasarkan firebase_uid
    current_user = None
    if hasattr(g, "firebase_user") and g.firebase_user:
        firebase_uid = g.firebase_user.get("uid")
        current_user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if current_user:
        user_entry = {
            "username": current_user.username,
            "points": int(current_user.points or 0),
            "profilePicture": current_user.profilePicture
        }

        # kalau user login tidak ada di top 15, tambahkan
        if not any(u["username"] == current_user.username for u in leaderboard):
            leaderboard.append(user_entry)

    return jsonify({'leaderboard': leaderboard}), 200


# ============================
# ROUTE: Submit Checklist
# ============================
@app.route('/submit-checklist', methods=['POST'])
@firebase_required
def submit_checklist():
    payload = request.get_json() or {}
    user = User.query.filter_by(firebase_uid=request.user_uid).first()

    if not user:
        return jsonify({'message': 'User not found'}), 404

    def to_int_bool(value):
        if isinstance(value, bool):
            return 1 if value else 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    checklist_data = {}
    for key in EMISSION_FACTORS.keys():
        raw_val = to_int_bool(payload.get(key))

        # untuk aktivitas negatif (semakin sedikit semakin baik) dibalik
        if key in ['packagedFood', 'onlineShopping', 'wasteFood', 'airConditioningHeating']:
            checklist_data[key] = 1 if raw_val == 1 else 0
        else:
            checklist_data[key] = raw_val

    total_kg = calculate_carbon_emissions(checklist_data)
    level = classify_level(total_kg)

    thirty_days_ago = date.today() - timedelta(days=30)
    historical_logs = DailyCarbonLog.query.filter(
        DailyCarbonLog.usersId == user.id,
        DailyCarbonLog.logDate >= thirty_days_ago
    ).all()

    car_km = float(payload.get('carTravelKm', 0))
    shower_min = float(payload.get('showerTimeMinutes', 0))
    electronic_hours = float(payload.get('electronicTimeHours', 0))

    normal_values = CarbonFuzzySystem.calculate_normal_values(historical_logs)
    fuzzy_analysis = CarbonFuzzySystem.fuzzy_system_analysis(
        car_km, shower_min, electronic_hours, normal_values
    )

    improvement_suggestions = generate_improvement_suggestions(payload)

    daily_log = DailyCarbonLog(
        usersId=user.id,
        totalCarbon=round(float(total_kg), 2),
        carbonLevel=level,
        IslandPath=level - 1,
        carbonSaved=int(payload.get("carbonSaved", 0)),
        logDate=date.today(),
        **checklist_data
    )
    db.session.add(daily_log)

    def should_save_numeric_goal(input_val, suggested_val, tolerance=0.1):
        return abs(float(input_val) - float(suggested_val)) > tolerance

    save_car_goal = should_save_numeric_goal(car_km, fuzzy_analysis['suggestions']['carTravelKm'])
    save_shower_goal = should_save_numeric_goal(shower_min, fuzzy_analysis['suggestions']['showerTimeMinutes'])
    save_electronic_goal = should_save_numeric_goal(electronic_hours, fuzzy_analysis['suggestions']['electronicTimeHours'])

    # boolean goals pakai nilai yg sudah dibalik
    save_packaged_food_goal = checklist_data['packagedFood'] == 1
    save_online_shopping_goal = checklist_data['onlineShopping'] == 1
    save_waste_food_goal = checklist_data['wasteFood'] == 1
    save_ac_heating_goal = checklist_data['airConditioningHeating'] == 1

    save_no_driving_goal = checklist_data['noDriving'] != 1
    save_plant_meal_goal = checklist_data['plantMealThanMeat'] != 1
    save_tumbler_goal = checklist_data['useTumbler'] != 1
    save_energy_goal = checklist_data['saveEnergy'] != 1
    save_recycle_goal = checklist_data['separateRecycleWaste'] != 1

    if (save_car_goal or save_shower_goal or save_electronic_goal or
        save_packaged_food_goal or save_online_shopping_goal or save_waste_food_goal or
        save_ac_heating_goal or save_no_driving_goal or save_plant_meal_goal or
        save_tumbler_goal or save_energy_goal or save_recycle_goal):

        goals_log = DailyGoalsLog(
            usersId=user.id,
            logDate=date.today(),
            carTravelKmGoal=fuzzy_analysis['suggestions']['carTravelKm'] if save_car_goal else None,
            showerTimeMinutesGoal=fuzzy_analysis['suggestions']['showerTimeMinutes'] if save_shower_goal else None,
            electronicTimeHoursGoal=fuzzy_analysis['suggestions']['electronicTimeHours'] if save_electronic_goal else None,
            packagedFoodGoal=0 if save_packaged_food_goal else None,
            onlineShoppingGoal=0 if save_online_shopping_goal else None,
            wasteFoodGoal=0 if save_waste_food_goal else None,
            airConditioningHeatingGoal=0 if save_ac_heating_goal else None,
            noDrivingGoal=1 if save_no_driving_goal else None,
            plantMealThanMeatGoal=1 if save_plant_meal_goal else None,
            useTumblerGoal=1 if save_tumbler_goal else None,
            saveEnergyGoal=1 if save_energy_goal else None,
            separateRecycleWasteGoal=1 if save_recycle_goal else None,
            suggestions=fuzzy_analysis['suggestions'] if (save_car_goal or save_shower_goal or save_electronic_goal) else None,
            improvement_suggestions=improvement_suggestions if improvement_suggestions else None
        )
        db.session.add(goals_log)

    db.session.commit()

    return jsonify({
        'totalcarbon': round(total_kg, 2),
        'carbonLevel': level,
        'emission_category': get_emission_category(level),
        'fuzzy_analysis': fuzzy_analysis,
        'improvement_suggestions': improvement_suggestions,
        'historical_data_points': len(historical_logs),
        'goals_saved': {
            'numeric_goals': save_car_goal or save_shower_goal or save_electronic_goal,
            'improvement_goals': len(improvement_suggestions) > 0
        }
    }), 201


# ============================
# ROUTE: Today Goals Completion
# ============================
@app.route('/check-goals-achieved', methods=['GET'])
@firebase_required
def check_goals_achieved():
    user = User.query.filter_by(firebase_uid=request.user_uid).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    today = date.today()
    yesterday = today - timedelta(days=1)

    # ambil log dan goals
    today_log = DailyCarbonLog.query.filter_by(usersId=user.id, logDate=today).first()
    yesterday_goals = DailyGoalsLog.query.filter_by(usersId=user.id, logDate=yesterday).first()

    if not today_log:
        return jsonify({'message': 'No carbon log found for today'}), 404
    if not yesterday_goals:
        return jsonify({'message': 'No goals found for yesterday'}), 404

    def check_goal_achieved(goal_val, actual_val, goal_type='numeric'):
        if goal_val is None:
            return None
        if goal_type == 'numeric':
            return actual_val <= goal_val
        elif goal_type == 'boolean':
            return actual_val == goal_val
        return False

    goals_achieved = {}       # hanya boolean goals
    numeric_results = {}      # untuk numeric goals (dengan nilai bool tercapai/tidak)
    points_to_add = 0

    # numeric goals
    numeric_goals_list = [
        ('carTravelKmGoal', 'carTravelKm'),
        ('showerTimeMinutesGoal', 'showerTimeMinutes'),
        ('electronicTimeHoursGoal', 'electronicTimeHours'),
    ]
    for goal_attr, log_attr in numeric_goals_list:
        goal_val = getattr(yesterday_goals, goal_attr)
        actual_val = getattr(today_log, log_attr)
        achieved = check_goal_achieved(goal_val, actual_val, 'numeric')
        numeric_results[goal_attr] = achieved  # masukkan hasil ke numeric_results
        if achieved:
            points_to_add += 5

    # boolean goals
    bool_goals = [
        ('packagedFoodGoal', 'packagedFood'),
        ('onlineShoppingGoal', 'onlineShopping'),
        ('wasteFoodGoal', 'wasteFood'),
        ('airConditioningHeatingGoal', 'airConditioningHeating'),
        ('noDrivingGoal', 'noDriving'),
        ('plantMealThanMeatGoal', 'plantMealThanMeat'),
        ('useTumblerGoal', 'useTumbler'),
        ('saveEnergyGoal', 'saveEnergy'),
        ('separateRecycleWasteGoal', 'separateRecycleWaste'),
    ]
    for goal_attr, log_attr in bool_goals:
        goal_val = getattr(yesterday_goals, goal_attr)
        actual_val = getattr(today_log, log_attr)
        achieved = check_goal_achieved(goal_val, actual_val, 'boolean')
        goals_achieved[log_attr] = achieved
        if achieved:
            points_to_add += 5

    # cek apakah sudah pernah tambah poin hari ini
    points_earned_today = 0
    if not user.last_points_added_date or user.last_points_added_date != today:
        if points_to_add > 0:
            user.points += points_to_add
            user.last_points_added_date = today
            db.session.commit()
            points_earned_today = points_to_add
    else:
        points_earned_today = 0  # sudah pernah tambah poin hari ini

    return jsonify({
        'date': str(today),
        'goals_achieved': goals_achieved,   # hanya boolean
        'numeric_goals': {                  # numeric tetap ada nilainya dan status tercapai
            'carTravelKmGoal': {
                'target': yesterday_goals.carTravelKmGoal,
                'achieved': numeric_results['carTravelKmGoal']
            },
            'showerTimeMinutesGoal': {
                'target': yesterday_goals.showerTimeMinutesGoal,
                'achieved': numeric_results['showerTimeMinutesGoal']
            },
            'electronicTimeHoursGoal': {
                'target': yesterday_goals.electronicTimeHoursGoal,
                'achieved': numeric_results['electronicTimeHoursGoal']
            },
        },
        'points_earned': points_earned_today,
        'total_points': user.points
    }), 200


# ============================
# ROUTE: Fecth latest goals
# ============================
@app.route('/latest-goals', methods=['GET'])
@firebase_required
def get_latest_goals():
    user = User.query.filter_by(firebase_uid=request.user_uid).first()

    if not user:
        return jsonify({'message': 'User not found'}), 404

    latest_goals = DailyGoalsLog.query \
        .filter_by(usersId=user.id) \
        .order_by(DailyGoalsLog.logDate.desc()) \
        .first()

    if not latest_goals:
        return jsonify({'message': 'No goal log found'}), 404

    combined_goals = []

    # ===== Numeric Goals =====
    numeric_definitions = [
        {
            'field': 'carTravelKmGoal',
            'title': 'Try limit your vehicle usage to',
            'unit': 'km'
        },
        {
            'field': 'showerTimeMinutesGoal',
            'title': 'Try limit your showers time to',
            'unit': 'minutes'
        },
        {
            'field': 'electronicTimeHoursGoal',
            'title': 'Try reduce your screen time to',
            'unit': 'hours'
        }
    ]

    for item in numeric_definitions:
        value = getattr(latest_goals, item['field'])
        if value is not None:
            combined_goals.append({
                'type': 'numeric',
                'field': item['field'],
                'title': item['title'],
                'value': value,
                'unit': item['unit']
            })

    # ===== Negative Checklist Goals (if value == 0 → needs improvement) =====
    negative_fields = {
        'packagedFoodGoal': 'Eat unpackaged or fresh food',
        'onlineShoppingGoal': 'Limit online shopping habits',
        'wasteFoodGoal': 'Avoid food waste',
        'airConditioningHeatingGoal': 'Reduce air conditioning or heating usage'
    }

    for field, title in negative_fields.items():
        if getattr(latest_goals, field) == 0:
            combined_goals.append({
                'type': 'negative',
                'field': field,
                'title': title
            })

    # ===== Positive Checklist Goals (if value == 1 → encourage to start doing) =====
    positive_fields = {
        'noDrivingGoal': 'Use environmentally friendly transportation',
        'plantMealThanMeatGoal': 'Eat more plant based meals',
        'useTumblerGoal': 'Bring your own tumbler or reusable bottle',
        'saveEnergyGoal': 'Practice energy saving at home',
        'separateRecycleWasteGoal': 'Separate waste for recycling'
    }

    for field, title in positive_fields.items():
        if getattr(latest_goals, field) == 1:
            combined_goals.append({
                'type': 'positive',
                'field': field,
                'title': title
            })

    return jsonify({
        'goals': combined_goals,
        'logDate': latest_goals.logDate.isoformat()
    }), 200
    

# ============================
# ROUTE: Check Today's Submission
# ============================
@app.route('/check-today-submission', methods=['GET'])
@firebase_required
def check_today_submission():
    user = User.query.filter_by(firebase_uid=request.user_uid).first()

    if not user:
        return jsonify({'message': 'User not found'}), 404

    today = datetime.now().date()

    submission = DailyCarbonLog.query.filter(
        DailyCarbonLog.usersId == user.id,
        DailyCarbonLog.logDate == today
    ).first()

    has_submitted = submission is not None

    return jsonify({
        'user_id': user.id,
        'date_checked': str(today),
        'has_submitted': has_submitted,
        'message': 'User has already submitted today' if has_submitted else 'No submission found for today'
    }), 200


# ============================
# ROUTE: Get Daily Carbon Logs
# ============================
@app.route('/daily-carbon-logs', methods=['GET'])
@firebase_required
def get_all_daily_carbon_logs():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        today_only = request.args.get('today_only', 'false').lower() == 'true'

        user = User.query.filter_by(firebase_uid=request.user_uid).first()
        if not user:
            return jsonify({"message": "User not found"}), 404

        query = DailyCarbonLog.query.filter(DailyCarbonLog.usersId == user.id)

        if today_only:
            today = date.today()
            query = query.filter(DailyCarbonLog.logDate == today)
        else:
            if date_from:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(DailyCarbonLog.logDate >= date_from_obj)
            if date_to:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(DailyCarbonLog.logDate <= date_to_obj)

        logs = query.order_by(desc(DailyCarbonLog.logDate)) \
                    .paginate(page=page, per_page=per_page, error_out=False)

        result = {
            "logs": [log.to_dict() for log in logs.items],
            "total_logs": logs.total,
            "current_page": logs.page,
            "per_page": logs.per_page,
            "total_pages": logs.pages
        }

        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            "message": "Failed to retrieve logs",
            "error": str(e)
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
