from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import openrouteservice
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from time import sleep
import folium
import sqlite3
import os

app = Flask(__name__)
app.secret_key = '828ebfe1d23cd0cba3105d4e285ff6902a25c47e0fda76e5'  # Replace with a secure key
client = openrouteservice.Client(key=os.getenv('ORS_API_KEY'))
geolocator = Nominatim(user_agent="tsp_web_app", timeout=10)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database setup
def init_db():
    with sqlite3.connect('instance/tsp.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            address TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        conn.commit()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect('instance/tsp.db') as conn:
        c = conn.cursor()
        c.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
        user = c.fetchone()
        if user:
            return User(user[0], user[1])
        return None

@app.route('/')
@login_required
def index():
    # Fetch user's saved locations
    with sqlite3.connect('instance/tsp.db') as conn:
        c = conn.cursor()
        c.execute('SELECT address FROM locations WHERE user_id = ?', (current_user.id,))
        saved_locations = [row[0] for row in c.fetchall()]
    return render_template('index.html', saved_locations=saved_locations)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect('instance/tsp.db') as conn:
            c = conn.cursor()
            c.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
            user = c.fetchone()
            if user and check_password_hash(user[2], password):
                login_user(User(user[0], user[1]))
                return redirect(url_for('index'))
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect('instance/tsp.db') as conn:
            c = conn.cursor()
            try:
                c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                          (username, generate_password_hash(password)))
                conn.commit()
                flash('Registration successful! Please log in.')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('Username already exists')
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/optimize', methods=['POST'])
@login_required
def optimize_route():
    addresses = request.json.get('addresses', [])
    if len(addresses) < 2:
        return jsonify({'error': 'At least two addresses are required.'}), 400

    # Save new addresses to database
    with sqlite3.connect('instance/tsp.db') as conn:
        c = conn.cursor()
        for address in addresses:
            c.execute('SELECT id FROM locations WHERE user_id = ? AND address = ?', (current_user.id, address))
            if not c.fetchone():
                c.execute('INSERT INTO locations (user_id, address) VALUES (?, ?)', (current_user.id, address))
        conn.commit()

    # Geocode addresses with retry
    coordinates = []
    for address in addresses:
        for attempt in range(3):
            try:
                location = geolocator.geocode(address, timeout=10)
                if location:
                    coordinates.append([location.longitude, location.latitude])
                    break
                else:
                    return jsonify({'error': f'Could not geocode address: {address}'}), 400
            except GeocoderTimedOut:
                if attempt < 2:
                    sleep(1)
                    continue
                return jsonify({'error': f'Geocoding timeout for address: {address}'}), 500
            except Exception as e:
                return jsonify({'error': f'Geocoding error: {str(e)}'}), 500
        sleep(1)

    # Route optimization logic (unchanged)
    start = coordinates[0]
    end = coordinates[-1]
    waypoints = coordinates[1:-1] if len(coordinates) > 2 else []
    if waypoints:
        matrix_coords = [start] + waypoints + [end]
        try:
            matrix = client.distance_matrix(
                locations=matrix_coords,
                profile='driving-car',
                metrics=['distance'],
                units='km'
            )
            distances = matrix['distances']
        except Exception as e:
            return jsonify({'error': f'API error: {str(e)}'}), 500
    else:
        distances = [[0, 0], [0, 0]]

    if waypoints:
        unvisited = list(range(1, len(coordinates) - 1))
        current = 0
        route = [0]
        total_distance = 0
        while unvisited:
            next_idx = min(unvisited, key=lambda x: distances[current][x])
            total_distance += distances[current][next_idx]
            route.append(next_idx)
            unvisited.remove(next_idx)
            current = next_idx
        route.append(len(coordinates) - 1)
        total_distance += distances[current][len(coordinates) - 1]
    else:
        route = [0, 1]
        total_distance = distances[0][1]

    try:
        optimized_coords = [coordinates[i] for i in route]
        route_request = client.directions(
            coordinates=optimized_coords,
            profile='driving-car',
            format='geojson'
        )
    except Exception as e:
        return jsonify({'error': f'Route error: {str(e)}'}), 500

    m = folium.Map(location=coordinates[0][::-1], zoom_start=10)
    folium.PolyLine(
        locations=[coord[::-1] for coord in route_request['features'][0]['geometry']['coordinates']],
        color='blue',
        weight=5
    ).add_to(m)
    for i, coord in enumerate(coordinates):
        folium.Marker(
            location=coord[::-1],
            popup=addresses[i],
            icon=folium.Icon(color='green' if i == 0 else 'red' if i == len(coordinates) - 1 else 'blue')
        ).add_to(m)
    map_html = m._repr_html_()

    route_summary = {
        'distance': f'{total_distance:.2f} km',
        'order': [addresses[i] for i in route]
    }
    return jsonify({'summary': route_summary, 'map_html': map_html})

if __name__ == '__main__':
    os.makedirs('instance', exist_ok=True)
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
