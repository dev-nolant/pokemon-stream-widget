import os
import re
import uuid
import secrets
import requests
import pytchat  # pip install pytchat
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# ------------------------------
# App & Extensions Setup
# ------------------------------
app = Flask(__name__)
# Sessions are signed with this key; set SECRET_KEY so logins survive restarts.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
# Use eventlet for asynchronous support in Socket.IO.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ------------------------------
# Database Model with widget_uuid
# ------------------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)  # internal username (lowercase)
    youtube = db.Column(db.String(120), nullable=False)               # YouTube username (as provided)
    password_hash = db.Column(db.String(128), nullable=False)
    pokemon = db.Column(db.String(80), nullable=False, default="pikachu")
    shiny = db.Column(db.Boolean, default=False)
    widget_uuid = db.Column(db.String(36), unique=True, nullable=False)  # Unique widget ID

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ------------------------------
# Sprite updates
# ------------------------------
POKEMON_NAME = re.compile(r'^[a-z0-9-]{1,40}$')

def sprite_url_for(pokemon, shiny):
    if shiny:
        return f"https://play.pokemonshowdown.com/sprites/xyani-shiny/{pokemon}.gif"
    return f"https://play.pokemonshowdown.com/sprites/ani/{pokemon}.gif"

def set_pokemon(user, pokemon, shiny):
    """Validate the name against Showdown's sprites, save it, and push it to the widget.
    Returns the sprite URL, or None if there's no such Pokemon."""
    pokemon = pokemon.lower()
    if not POKEMON_NAME.match(pokemon):
        return None
    sprite_url = sprite_url_for(pokemon, shiny)
    try:
        if requests.head(sprite_url, timeout=5).status_code != 200:
            return None
    except requests.RequestException:
        return None
    user.pokemon = pokemon
    user.shiny = shiny
    db.session.commit()
    socketio.emit('pokemon_update', {
        "pokemon": pokemon,
        "shiny": shiny,
        "sprite_url": sprite_url
    }, room=user.widget_uuid)
    return sprite_url

# ------------------------------
# Routes
# ------------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        youtube = request.form.get('youtube', '').strip()
        password = request.form.get('password', '')
        if not username or not youtube or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash("Username already exists!", "danger")
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            youtube=youtube,
            pokemon="pikachu",
            shiny=False,
            widget_uuid=str(uuid.uuid4())
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash("Registration successful!", "success")
        return redirect(url_for('dashboard'))
    return render_template('registration.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for('login'))
        login_user(user)
        flash("Logged in successfully.", "success")
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

# New Edit Profile Route
@app.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    if request.method == 'POST':
        new_youtube = request.form.get('youtube', '').strip()
        new_password = request.form.get('password', '')
        if not new_youtube:
            flash("YouTube username cannot be empty.", "danger")
            return redirect(url_for('edit'))
        current_user.youtube = new_youtube
        if new_password:
            current_user.set_password(new_password)
        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for('dashboard'))
    return render_template('edit.html')

# Widget route (accessed via widget_uuid)
@app.route('/widget/<widget_uuid>')
def widget(widget_uuid):
    user = User.query.filter_by(widget_uuid=widget_uuid).first()
    if not user:
        return "User not found!", 404
    sprite_url = sprite_url_for(user.pokemon, user.shiny)
    return render_template('widget.html',
                           sprite_url=sprite_url,
                           widget_uuid=user.widget_uuid)

# Same as typing the chat command, for testing without a live stream.
# Only changes the logged-in user's own widget.
@app.route('/command', methods=['POST'])
@login_required
def command():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON provided"}), 400
    parts = data.get("command", "").strip().split()
    if len(parts) < 2 or parts[0].lower() != "!pokemon":
        return jsonify({"error": "Invalid command format. Use: !pokemon <pokemon> [shiny]"}), 400
    shiny = len(parts) > 2 and parts[2].lower() == "shiny"
    if not set_pokemon(current_user, parts[1], shiny):
        return jsonify({"error": "Invalid Pokémon name"}), 400
    return jsonify({"message": f"Updated Pokémon to {current_user.pokemon} ({'shiny' if shiny else 'normal'})."})

# ------------------------------
# Socket.IO Event Handlers
# ------------------------------
@socketio.on('join')
def on_join(data):
    widget_uuid = data.get('widget_uuid')
    if widget_uuid:
        join_room(widget_uuid)
        app.logger.info(f"Client joined room {widget_uuid}")
        emit('joined', {'message': f'Joined room {widget_uuid}'})
    else:
        emit('error', {'message': 'widget_uuid is required to join a room.'})

# ------------------------------
# Background Task: YouTube Chat Listener using pytchat
# ------------------------------
def chat_listener():
    video_id = os.environ.get("YOUTUBE_VIDEO_ID")
    if not video_id:
        app.logger.warning("YOUTUBE_VIDEO_ID not set; chat commands are disabled.")
        return
    try:
        chat = pytchat.create(video_id=video_id)
    except Exception as e:
        app.logger.error("Failed to create pytchat: " + str(e))
        return
    app.logger.info("Started YouTube chat listener for video_id: " + video_id)
    while chat.is_alive():
        for c in chat.get().sync_items():
            parts = c.message.strip().split()
            if len(parts) < 2 or parts[0].lower() != "!pokemon":
                continue
            shiny = len(parts) > 2 and parts[2].lower() == "shiny"
            youtube_author = c.author.name.strip().lower()
            with app.app_context():
                user = User.query.filter(User.youtube.ilike(youtube_author)).first()
                if user and set_pokemon(user, parts[1], shiny):
                    app.logger.info(f"Updated {user.username} from chat command by {c.author.name}")
        socketio.sleep(1)

# ------------------------------
# Main Entry Point
# ------------------------------
if __name__ == '__main__':
    socketio.start_background_task(chat_listener)
    socketio.run(app,
                 debug=os.environ.get('FLASK_DEBUG') == '1',
                 host='0.0.0.0',
                 port=int(os.environ.get('PORT', 8080)))
