import sys
import logging

# ── Startup debug logging ──────────────────────────────────────────────────
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format='[%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

log.info("=== APP STARTUP ===")
log.info(f"Python version: {sys.version}")

from flask import Flask, render_template, request, jsonify, send_from_directory
log.info("Flask imported OK")

import requests
log.info("requests imported OK")

import math, re, os
from werkzeug.utils import secure_filename
log.info("werkzeug imported OK")

try:
    import fitz  # PyMuPDF
    log.info(f"PyMuPDF (fitz) imported OK — version {fitz.version}")
except ImportError as e:
    log.error(f"FAILED to import PyMuPDF (fitz): {e}")
    fitz = None

app = Flask(__name__)

# Use /tmp so it works on read-only filesystems (Render, Heroku, etc.)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
log.info(f"Upload folder ready: {app.config['UPLOAD_FOLDER']}")
log.info("=== APP READY ===")

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def extract_addresses_from_text(text):
    """Extract addresses from Quebec-formatted PDFs"""
    addresses = []
    
    # Split text into lines and clean them
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    print(f"DEBUG: Total lines extracted: {len(lines)}")
    print(f"DEBUG: First 30 lines:")
    for i, line in enumerate(lines[:30]):
        print(f"  Line {i}: {line}")
    
    # Look for "Adresse:" or "Adresse :" markers (case insensitive, with or without colon)
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Check if this line contains "adresse" (with or without colon, with or without space)
        if 'adresse' in line_lower and i + 3 < len(lines):
            print(f"\nDEBUG: Found 'Adresse' at line {i}: {line}")
            
            # Extract the next lines after "Adresse:"
            street = lines[i + 1].strip()
            postal_line = lines[i + 2].strip()
            city_line = lines[i + 3].strip()
            
            print(f"DEBUG: Street (line {i+1}): {street}")
            
            # Clean up address range (e.g., 4472-4476 or 4062-4062A becomes 4476 or 4062A)
            # Match pattern: digits[letter]-digits[letter] followed by street name
            original_street = street
            range_match = re.match(r'^\d+[A-Z]?\s*-\s*(\d+[A-Z]?\s+.+)$', street, re.IGNORECASE)
            if range_match:
                street = range_match.group(1).strip()
                print(f"DEBUG: Cleaned address range: '{original_street}' → '{street}'")
            else:
                print(f"DEBUG: No address range pattern found in: '{street}'")
            
            # Handle semicolon - only use the first address
            if ';' in street:
                original_with_semi = street
                street = street.split(';')[0].strip()
                print(f"DEBUG: Removed semicolon, using first address: '{original_with_semi}' → '{street}'")
            
            # Replace ST/STE abbreviations with Saint/Sainte
            # Use word boundaries to avoid replacing ST in other contexts
            original_before_abbrev = street
            street = re.sub(r'\bST\b', 'SAINT', street, flags=re.IGNORECASE)
            street = re.sub(r'\bSTE\b', 'SAINTE', street, flags=re.IGNORECASE)
            
            # Replace compass direction abbreviations (single letters)
            # N, S, O, E → Nord, Sud, Ouest, Est
            street = re.sub(r'\bN\b', 'NORD', street, flags=re.IGNORECASE)
            street = re.sub(r'\bS\b', 'SUD', street, flags=re.IGNORECASE)
            street = re.sub(r'\bO\b', 'OUEST', street, flags=re.IGNORECASE)
            street = re.sub(r'\bE\b', 'EST', street, flags=re.IGNORECASE)
            
            if original_before_abbrev != street:
                print(f"DEBUG: Replaced abbreviations: '{original_before_abbrev}' → '{street}'")
            
            print(f"DEBUG: Postal (line {i+2}): {postal_line}")
            print(f"DEBUG: City line (line {i+3}): {city_line}")
            
            # Skip if street is empty or too short (check after range cleaning)
            if not street or len(street) < 5:
                print(f"DEBUG: Skipping - street too short or empty")
                continue
            
            # Clean up postal code line - extract only the postal code (format: H2J2J3 or H2J 2J3)
            postal_code = ''
            postal_match = re.search(r'([A-Z]\d[A-Z]\s?\d[A-Z]\d)', postal_line, re.IGNORECASE)
            if postal_match:
                postal_code = postal_match.group(1).upper()
                # Normalize format (add space if missing)
                if len(postal_code) == 6:
                    postal_code = f"{postal_code[:3]} {postal_code[3:]}"
                print(f"DEBUG: Extracted postal code: {postal_code}")
            else:
                print(f"DEBUG: No postal code found in: {postal_line}")
            
            # Extract city name
            city = ''
            
            # Check if city_line is just "Ville:" without the city name
            if city_line.lower().strip() in ['ville:', 'ville']:
                # City is on the next line
                if i + 4 < len(lines):
                    city = lines[i + 4].strip()
                    print(f"DEBUG: 'Ville:' on separate line, city from line {i+4}: {city}")
            elif 'ville' in city_line.lower():
                # City is on the same line as "Ville:"
                # Remove "Ville:" or "ville:" prefix
                city = re.sub(r'Ville\s*:\s*', '', city_line, flags=re.IGNORECASE).strip()
                print(f"DEBUG: Extracted city from same line: {city}")
            else:
                # If no "Ville:" marker, try to use the line as-is
                city = city_line
                print(f"DEBUG: Using line as city (no 'Ville:' marker): {city}")
            
            # Remove parentheses content (e.g., "(PLATEAU MONT-ROYAL)")
            if '(' in city:
                city = city.split('(')[0].strip()
                print(f"DEBUG: Removed parentheses, final city: {city}")
            
            # Build complete address
            if street and city:
                # Format: Street, City, Postal Code, Quebec, Canada
                if postal_code:
                    full_address = f"{street}, {city}, {postal_code}, Quebec, Canada"
                else:
                    full_address = f"{street}, {city}, Quebec, Canada"
                
                # Clean up any double spaces or commas
                full_address = re.sub(r'\s+', ' ', full_address)
                full_address = re.sub(r',\s*,', ',', full_address)
                full_address = full_address.strip(', ')
                
                print(f"DEBUG: Built address: {full_address}")
                
                if full_address not in addresses:
                    addresses.append(full_address)
                    print(f"DEBUG: Added address #{len(addresses)}")
                else:
                    print(f"DEBUG: Duplicate address, skipped")
    
    print(f"\nDEBUG: Total addresses found: {len(addresses)}")
    for i, addr in enumerate(addresses):
        print(f"  {i+1}. {addr}")
    
    return addresses[:150]  # Limit to 150 addresses

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF file using PyMuPDF (fitz)"""
    if fitz is None:
        raise Exception("PyMuPDF is not installed on this server. Check deploy logs.")
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text
    except Exception as e:
        raise Exception(f"Error reading PDF: {str(e)}")

def optimize_route(locations, start_index=None, end_index=None):
    """Optimize route using nearest neighbor algorithm with optional start/end constraints"""
    if len(locations) <= 2:
        return locations
    
    # If we have start/end constraints, handle them
    if start_index is not None or end_index is not None:
        # Build list of locations we'll optimize
        available = list(range(len(locations)))
        
        # Determine start location
        if start_index is not None:
            start_loc = locations[start_index]
            available.remove(start_index)
        else:
            # No start specified, use first location
            start_loc = locations[0]
            available.remove(0)
        
        # Determine end location (remove from available if specified)
        end_loc = None
        if end_index is not None:
            end_loc = locations[end_index]
            if end_index in available:
                available.remove(end_index)
        
        # Build route starting from start point
        route = [start_loc]
        
        # Use nearest neighbor for middle points
        while available:
            current = route[-1]
            nearest_idx = None
            shortest_distance = float('inf')
            
            for idx in available:
                loc = locations[idx]
                distance = calculate_distance(
                    current['lat'], current['lon'],
                    loc['lat'], loc['lon']
                )
                if distance < shortest_distance:
                    shortest_distance = distance
                    nearest_idx = idx
            
            route.append(locations[nearest_idx])
            available.remove(nearest_idx)
        
        # Add end point if specified
        if end_loc is not None:
            route.append(end_loc)
        
        return route
    else:
        # No constraints - standard nearest neighbor from first location
        route = [locations[0]]
        remaining_indices = list(range(1, len(locations)))
        
        while remaining_indices:
            current = route[-1]
            nearest_idx = None
            shortest_distance = float('inf')
            
            for idx in remaining_indices:
                loc = locations[idx]
                distance = calculate_distance(
                    current['lat'], current['lon'],
                    loc['lat'], loc['lon']
                )
                if distance < shortest_distance:
                    shortest_distance = distance
                    nearest_idx = idx
            
            route.append(locations[nearest_idx])
            remaining_indices.remove(nearest_idx)
        
        return route

def calculate_total_distance(route):
    """Calculate total distance of the route"""
    total = 0
    for i in range(len(route) - 1):
        total += calculate_distance(
            route[i]['lat'], route[i]['lon'],
            route[i + 1]['lat'], route[i + 1]['lon']
        )
    return round(total, 2)

@app.route('/health')
def health():
    """Simple health check — useful for diagnosing 502s"""
    return jsonify({
        'status': 'ok',
        'python': sys.version,
        'pymupdf': str(fitz.version) if fitz else 'NOT INSTALLED'
    })

@app.route('/')
def index():
    """Serve the main page - works whether index.html is in root or templates/"""
    # Try templates folder first, fall back to current directory
    templates_path = os.path.join(os.path.dirname(__file__), 'templates', 'index.html')
    root_path = os.path.join(os.path.dirname(__file__), 'index.html')
    
    if os.path.exists(templates_path):
        return send_from_directory(os.path.join(os.path.dirname(__file__), 'templates'), 'index.html')
    elif os.path.exists(root_path):
        return send_from_directory(os.path.dirname(__file__) or '.', 'index.html')
    else:
        return "index.html not found. Place it in the project root or a templates/ folder.", 404

@app.route('/upload-pdf', methods=['POST'])
def upload_pdf():
    """Handle PDF upload and extract addresses"""
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        return jsonify({'error': 'No files selected'}), 400
    
    all_addresses = []
    
    try:
        for file in files:
            if file and file.filename.lower().endswith('.pdf'):
                # Save file temporarily
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                # Extract text
                text = extract_text_from_pdf(filepath)
                
                # Extract addresses
                addresses = extract_addresses_from_text(text)
                
                # Add source PDF info to each address
                pdf_name = filename.replace('.pdf', '').replace('.PDF', '')
                for addr in addresses:
                    all_addresses.append({
                        'address': addr,
                        'source': pdf_name
                    })
                
                # Clean up
                os.remove(filepath)
        
        return jsonify({
            'addresses': all_addresses,
            'count': len(all_addresses)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/geocode', methods=['POST'])
def geocode():
    """Geocode a single address"""
    data = request.json
    address = data.get('address', '')
    
    if not address:
        return jsonify({'error': 'Address is required'}), 400
    
    try:
        # Use Nominatim API for geocoding
        response = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={
                'format': 'json',
                'q': address,
                'limit': 1
            },
            headers={'User-Agent': 'RouteOptimizer/1.0'}
        )
        
        data = response.json()
        
        if not data:
            return jsonify({'error': f'Could not find: {address}'}), 404
        
        result = data[0]
        return jsonify({
            'lat': float(result['lat']),
            'lon': float(result['lon']),
            'display_name': result['display_name']
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import time

# Simple in-memory cache for geocoding
geocode_cache = {}

@app.route('/optimize', methods=['POST'])
def optimize():
    """Optimize route for multiple addresses safely"""
    data = request.json
    addresses = data.get('addresses', [])
    start_point = data.get('start_point')  # Index of start point (or None)
    end_point = data.get('end_point')      # Index of end point (or None)
    pre_geocoded = data.get('pre_geocoded', [])  # Optional pre-resolved coords from client

    # Filter out empty addresses
    addresses = [addr.strip() for addr in addresses if addr.strip()]
    if len(addresses) < 2:
        return jsonify({'error': 'Please provide at least 2 addresses'}), 400

    locations = []

    for idx, address in enumerate(addresses):
        # Use pre-geocoded coords if provided and valid
        if pre_geocoded and idx < len(pre_geocoded) and pre_geocoded[idx]:
            pg = pre_geocoded[idx]
            loc = {
                'lat': float(pg['lat']),
                'lon': float(pg['lon']),
                'display_name': pg.get('display_name', address)
            }
            locations.append({**loc, 'original_address': address, 'original_index': idx})
            continue

        # Check cache first
        if address in geocode_cache:
            locations.append({**geocode_cache[address], 'original_address': address, 'original_index': idx})
            continue

        # Determine search query
        postal_match = re.search(r'([A-Z]\d[A-Z]\s?\d[A-Z]\d)', address, re.IGNORECASE)
        if postal_match:
            postal_code = postal_match.group(1)
            search_query = f"{postal_code}, Quebec, Canada"
        else:
            search_query = address

        # Function to safely query Nominatim
        def geocode(query):
            try:
                response = requests.get(
                    'https://nominatim.openstreetmap.org/search',
                    params={'format': 'json', 'q': query, 'limit': 1},
                    headers={'User-Agent': 'RouteOptimizer/1.0'},
                    timeout=10
                )
                if response.status_code != 200:
                    return None
                try:
                    data = response.json()
                except ValueError:
                    return None
                return data
            except Exception as e:
                return None

        # First attempt
        result = geocode(search_query)
        time.sleep(1)

        # Fallback to full address if postal code search failed
        if (not result or len(result) == 0) and postal_match:
            result = geocode(address)
            time.sleep(1)

        if not result or len(result) == 0:
            return jsonify({'error': f'Could not find: {address}'}), 404

        loc = {
            'lat': float(result[0]['lat']),
            'lon': float(result[0]['lon']),
            'display_name': result[0]['display_name']
        }
        geocode_cache[address] = loc

        locations.append({**loc, 'original_address': address, 'original_index': idx})

    # Optimize the route
    optimized_route = optimize_route(locations, start_point, end_point)
    total_distance = calculate_total_distance(optimized_route)

    return jsonify({
        'route': optimized_route,
        'total_distance': total_distance
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)