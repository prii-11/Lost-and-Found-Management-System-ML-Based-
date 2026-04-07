from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from app.database import Database
import os
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'shhhhh')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


db = Database()

class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data['user_id']
        self.username = user_data['username']
        self.email = user_data['email']
        self.full_name = user_data['full_name']
        self.role = user_data['role']
        self.phone = user_data.get('phone')

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(int(user_id))
    if user_data:
        return User(user_data)
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'student':
            flash('Access denied. Student privileges required.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_match_score(lost_item, found_item):
    score = 0
    total_weight = 0
    
    if lost_item['category'].lower() == found_item['category'].lower():
        score += 30
    total_weight += 30
    
    lost_name = lost_item['item_name'].lower()
    found_name = found_item['item_name'].lower()
    if lost_name in found_name or found_name in lost_name:
        score += 25
    elif any(word in found_name for word in lost_name.split()):
        score += 15
    total_weight += 25
    
    lost_desc = lost_item['description'].lower()
    found_desc = found_item['description'].lower()
    common_words = set(lost_desc.split()) & set(found_desc.split())
    if len(common_words) > 0:
        score += min(20, len(common_words) * 2)
    total_weight += 20
    
    if lost_item['location_lost'].lower() in found_item['location_found'].lower() or \
       found_item['location_found'].lower() in lost_item['location_lost'].lower():
        score += 15
    total_weight += 15
    
    try:
        date_diff = abs((lost_item['date_lost'] - found_item['date_found']).days)
        if date_diff <= 1:
            score += 10
        elif date_diff <= 7:
            score += 5
        elif date_diff <= 14:
            score += 2
    except:
        pass
    total_weight += 10
    
    match_percentage = (score / total_weight) * 100
    return round(match_percentage, 2)

def find_and_create_matches(item_id, item_type='lost'):
    matches = []
    
    if item_type == 'lost':
        lost_items = [db.get_lost_items_by_user(current_user.id)]
        lost_item = None
        for items_list in lost_items:
            for item in items_list:
                if item['lost_id'] == item_id:
                    lost_item = item
                    break
        
        if not lost_item:
            return []
        
        found_items = db.get_all_found_items()
        
        for found_item in found_items:
            if found_item['status'] == 'unclaimed':
                match_score = calculate_match_score(lost_item, found_item)
                
                if match_score >= 40:
                    match_id = db.create_match(lost_item['lost_id'], found_item['found_id'], match_score)
                    
                    db.create_notification(
                        current_user.id,
                        match_id,
                        f"Potential match found for your lost {lost_item['item_name']}! Match score: {match_score}%"
                    )
                    
                    db.create_notification(
                        found_item['user_id'],
                        match_id,
                        f"Your found {found_item['item_name']} may match a lost item! Match score: {match_score}%"
                    )
                    
                    matches.append({
                        'match_id': match_id,
                        'found_item': found_item,
                        'match_score': match_score
                    })
    
    elif item_type == 'found':
        found_item = db.get_found_item_by_id(item_id)
        
        if not found_item:
            return []
        
        lost_items = db.get_all_lost_items()
        
        for lost_item in lost_items:
            if lost_item['status'] == 'unfound':
                match_score = calculate_match_score(lost_item, found_item)
                
                if match_score >= 40:
                    match_id = db.create_match(lost_item['lost_id'], found_item['found_id'], match_score)
                    
                    db.create_notification(
                        current_user.id,
                        match_id,
                        f"Your found {found_item['item_name']} may match a lost item! Match score: {match_score}%"
                    )
                    
                    db.create_notification(
                        lost_item['user_id'],
                        match_id,
                        f"Potential match found for your lost {lost_item['item_name']}! Match score: {match_score}%"
                    )
                    
                    matches.append({
                        'match_id': match_id,
                        'lost_item': lost_item,
                        'match_score': match_score
                    })
    
    return matches

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db.get_user_by_username(username)
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(user_data)
            login_user(user)
            db.update_last_login(user.id)
            
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        role = request.form.get('role', 'student')
        
        if role not in ['student', 'admin']:
            role = 'student'
        
        try:
            password_hash = generate_password_hash(password)
            user_id = db.create_user(username, email, password_hash, full_name, role, phone)
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    lost_items = db.get_lost_items_by_user(current_user.id)
    found_items = db.get_found_items_by_user(current_user.id)
    notifications = db.get_user_notifications(current_user.id)
    
    return render_template('student_dashboard.html', 
                         lost_items=lost_items,
                         found_items=found_items,
                         notifications=notifications)

@app.route('/student/report_lost', methods=['POST'])
@login_required
@student_required
def report_lost():
    try:
        item_name = request.form.get('item_name')
        category = request.form.get('category')
        description = request.form.get('description')
        location_lost = request.form.get('location_lost')
        date_lost = request.form.get('date_lost')
        
        lost_id = db.create_lost_item(current_user.id, item_name, category, description, location_lost, date_lost)
        
        find_and_create_matches(lost_id, 'lost')
        
        flash(f'Lost item "{item_name}" reported successfully!', 'success')
    except Exception as e:
        flash(f'Error reporting lost item: {str(e)}', 'error')
    
    return redirect(url_for('student_dashboard'))

@app.route('/student/report_found', methods=['POST'])
@login_required
@student_required
def report_found():
    try:
        item_name = request.form.get('item_name')
        category = request.form.get('category')
        description = request.form.get('description')
        location_found = request.form.get('location_found')
        date_found = request.form.get('date_found')
        
        found_id = db.create_found_item(current_user.id, item_name, category, description, location_found, date_found)
        
        find_and_create_matches(found_id, 'found')
        
        flash(f'Found item "{item_name}" reported successfully!', 'success')
    except Exception as e:
        flash(f'Error reporting found item: {str(e)}', 'error')
    
    return redirect(url_for('student_dashboard'))

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    lost_items = db.get_all_lost_items()
    found_items = db.get_all_found_items()
    users = db.get_all_users()
    stats = db.get_statistics()
    
    return render_template('admin_dashboard.html',
                         lost_items=lost_items,
                         found_items=found_items,
                         users=users,
                         stats=stats)

@app.route('/admin/update_lost_status', methods=['POST'])
@login_required
@admin_required
def update_lost_status():
    try:
        lost_id = request.form.get('lost_id')
        status = request.form.get('status')
        
        db.update_lost_item_status(lost_id, status)
        flash('Lost item status updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating status: {str(e)}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_found_status', methods=['POST'])
@login_required
@admin_required
def update_found_status():
    try:
        found_id = request.form.get('found_id')
        status = request.form.get('status')
        
        db.update_found_item_status(found_id, status)
        flash('Found item status updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating status: {str(e)}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/notifications/mark_read/<int:notification_id>')
@login_required
def mark_notification_read(notification_id):
    db.mark_notification_read(notification_id)
    return redirect(request.referrer or url_for('index'))

@app.route('/notifications/mark_all_read')
@login_required
def mark_all_read():
    db.mark_all_notifications_read(current_user.id)
    flash('All notifications marked as read.', 'success')
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
