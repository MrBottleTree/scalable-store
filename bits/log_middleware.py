import logging
import requests
from datetime import datetime
from bits.models import Person
from user_agents import parse
from math import radians, sin, cos, sqrt, atan2
import threading

BITS_CAMPUSES = {
    'GOA': (15.3911442733276, 73.87815086678745),
    'HYD': (17.544822002003123, 78.57271655444397),
    'PIL': (28.359229729445914, 75.58816379595879),
    'DUB': (25.131566983306616, 55.4200293516723),
}

HEADERS = {"User-Agent": "Mozilla/5.0 (BITSGeolocator/1.0)"}

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("bits")

    def __call__(self, request):
        email = None
        person = None
        person_info = "-1 None"

        email = request.session.get('email')
        name = request.session.get('name')
        if email:
            person_info = email
        person = Person.objects.filter(email=email).first()
        if person:
            person_info = f"{person.id}, {person.name}"

        ip = self.get_client_ip(request)
        path = request.get_full_path()
        method = request.method
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        user_agent = parse(ua_string)
        browser = f"{user_agent.browser.family} {user_agent.browser.version_string}"
        os = f"{user_agent.os.family} {user_agent.os.version_string}"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lat_str = "None"
        lon_str = "None"

        def get_campus():
            lat, lon = self.get_location(ip)
            lat_str = f"{lat}" if lat is not None else "None"
            lon_str = f"{lon}" if lon is not None else "None"
            campus = self.get_nearest_campus(lat, lon)
            log_message = (
                f"{timestamp} | {method} | {person_info} | {path} | {ip} | {os} | {browser} | "
                f"{lat_str} | {lon_str} | {campus} | {person.campus if person else campus}"
            )
            self.logger.info(log_message)
            return campus

        if person is not None and person.campus == "OTH":
            person.campus = get_campus()
            person.save()

        elif not person and email:
            Person.objects.create(email = email, campus = get_campus(), name = "Unknown" if not name else name)
        
        else:
            threading.Thread(target=get_campus).start()

        return self.get_response(request)

    def get_client_ip(self, request):
        return request.META.get('HTTP_CF_CONNECTING_IP') or (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        ) or request.META.get('REMOTE_ADDR')

    def get_location(self, ip):
        try:
            url = f"https://api.ipregistry.co/{ip}?key=tryout"
            res = requests.get(url, headers=HEADERS, timeout=2).json()
            loc = res.get("location", {})
            ret = (float(loc.get("latitude")), float(loc.get("longitude")))
            return ret
        except Exception as e:
            return self.get_location2(ip)

    def get_location2(self, ip):
        try:
            url = f"https://ipinfo.io/{ip}/json"
            res = requests.get(url, headers=HEADERS, timeout=2).json()
            if "loc" in res:
                lat_str, lon_str = res["loc"].split(",")
                ret = float(lat_str), float(lon_str)
                return ret
            else:
                return self.get_location3(ip)
        except Exception as e:
            return self.get_location3(ip)

    def get_location3(self, ip):
        try:
            url = f"https://api.ipdata.co/{ip}?api-key=test"
            res = requests.get(url, headers=HEADERS, timeout=2).json()
            ret = (float(res.get("latitude")), float(res.get("longitude")))
            return ret
        except Exception as e:
            return self.get_location4(ip)

    def get_location4(self, ip):
        try:
            url = f"http://ip-api.com/json/{ip}"
            res = requests.get(url, headers=HEADERS, timeout=2).json()
            ret = (float(res.get("lat")), float(res.get("lon")))
            return ret
        except Exception as e:
            return None, None

    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    def get_nearest_campus(self, lat, lon):
        if lat is None or lon is None:
            return "OTH"

        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return "OTH"

        min_dist = float('inf')
        nearest = "OTH"
        for campus, (clat, clon) in BITS_CAMPUSES.items():
            dist = self.haversine(lat, lon, clat, clon)
            if dist < min_dist:
                min_dist = dist
                nearest = campus
        return nearest