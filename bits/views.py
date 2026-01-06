banned_list = []
NOTIFICATION_COOLDOWN = 10 #minutes nigga

import os
import json
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.shortcuts import render
import hashlib
import time
from django.core.cache import cache
from django.middleware.csrf import get_token
from collections import Counter
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import *
from django.utils import timezone
from django import forms
from django.conf import settings
from . import helper
from datetime import datetime, timedelta
from django.db.models import Q, Count, Prefetch
from django.core.signing import Signer
import re


signer = Signer()


VAPID_PRIVATE_KEY = "rPXaPhy_BNi0K0TKv1XpXFhR0Zfs2VbxnMDef51Lc8Q"
VAPID_CLAIMS = {
    "sub": "mailto:vishrut172@gmail.com"
}

LOGFILE = os.path.join(settings.LOG_DIR, 'request_logs.log')

METRICS = {
    'requests': {
        'label': 'Number of Requests',
        'extractor': lambda e: True,
    },
    'unique_visitors': {
        'label': 'Unique Visitors',
        'extractor': lambda e: e['ip'],
    },
    'registered_requests': {
        'label': 'Registered Requests',
        'extractor': lambda e: e['person'] != "-1 None",
    },
    'unique_registered_visitors': {
        'label': 'Unique Registered Visitors',
        'extractor': lambda e: e['ip'] if e['person'] != "-1 None" else False,
    },
    'items_added': {
        'label': 'Items Added',
        'extractor': lambda e: e['method'] == 'POST' and e['path'].startswith('/add-product'),
    },
    'items_updated': {
        'label': 'Items Updated',
        'extractor': lambda e: e['method'] == 'POST' and (e['path'].startswith('/bulk-action/') or e['path'].startswith('/repost') or e['path'].startswith('/edit-item') or e['path'].startswith('/delete-item') or e['path'].startswith('/marksold')),
    },
}

class AnalyticsForm(forms.Form):
    metric_y = forms.ChoiceField(label="Y-axis", choices=[(k, METRICS[k]['label']) for k in METRICS])
    start_time = forms.DateTimeField(label="From", initial=lambda: timezone.now() - timedelta(days=7))
    end_time = forms.DateTimeField(label="To", initial=lambda: timezone.now())
    buckets = forms.IntegerField(label="# of points", min_value=2, max_value=1000, initial=84)
    show_map = forms.BooleanField(label="Show Map", required=False, initial=True)
    map_window = forms.IntegerField(label="Map: last N minutes", min_value=1, initial=10080)

def parse_log_line(line):
    parts = [p.strip() for p in line.split('|')]
    if len(parts) < 11:
        return None
    
    try:
        ts = datetime.strptime(parts[0], '%Y-%m-%d %H:%M:%S')
        ts = timezone.make_aware(ts, timezone.get_default_timezone())
    except:
        return None

    def parse_coord(coord_str):
        if coord_str == "None" or not coord_str:
            return None
        try:
            return float(coord_str)
        except:
            return None

    return {
        'timestamp': ts,
        'method': parts[1],
        'person': parts[2],
        'path': parts[3],
        'ip': parts[4],
        'os': parts[5],
        'browser': parts[6],
        'lat': parse_coord(parts[7]),
        'lon': parse_coord(parts[8]),
        'campus': parts[9],
        'person_campus': parts[10] if len(parts) > 10 else None,
    }

def analytics(request):
    form = AnalyticsForm(request.GET or None)
    chart_data = None
    map_points = []
    summary = {}
    os_dist = Counter()
    browser_dist = Counter()
    hourly_hits = [0]*24
    top_paths = Counter()
    campus_dist = Counter()

    if form.is_valid():
        cd = form.cleaned_data
        entries = []
        try:
            with open(LOGFILE, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    e = parse_log_line(line)
                    if not e:
                        continue
                    if not (cd['start_time'] <= e['timestamp'] <= cd['end_time']):
                        continue
                    entries.append(e)
        except FileNotFoundError:
            entries = []
        except Exception as e:
            print(f"Error reading log file: {e}")
            entries = []

        total_secs = (cd['end_time'] - cd['start_time']).total_seconds()
        step = total_secs / cd['buckets']
        seen = [set() for _ in range(cd['buckets'])]
        counts = [0] * cd['buckets']
        metric = METRICS[cd['metric_y']]

        for e in entries:
            age = (e['timestamp'] - cd['start_time']).total_seconds()
            idx = min(int(age // step), cd['buckets'] - 1)
            val = metric['extractor'](e)
            if isinstance(val, bool):
                if val:
                    counts[idx] += 1
            else:
                seen[idx].add(val)

            os_dist[e['os']] += 1
            browser_dist[e['browser']] += 1
            hourly_hits[e['timestamp'].hour] += 1
            top_paths[e['path']] += 1
            campus_dist[e['campus']] += 1

        if cd['metric_y'].startswith('unique'):
            counts = [len(s) for s in seen]

        labels = [
            (cd['start_time'] + timedelta(seconds=step * i)).strftime('%H:%M')
            for i in range(cd['buckets'])
        ]
        chart_data = {
            'labels': labels,
            'dataset': {
                'label': metric['label'],
                'data': counts,
            }
        }

        summary = {
            'total_requests': len(entries),
            'returning_visitors': sum(1 for c in Counter(e['ip'] for e in entries).values() if c > 1),
            'os_distribution': dict(os_dist.most_common()),
            'browser_distribution': dict(browser_dist.most_common()),
            'hourly_hits': hourly_hits,
            'top_paths': dict(top_paths.most_common(10)),
            'campus_distribution': dict(campus_dist.most_common()),
        }

        if cd['show_map']:
            cutoff = timezone.now() - timedelta(minutes=cd['map_window'])
            recent = [e for e in entries if e['timestamp'] >= cutoff]
            seen_ips = set()
            for e in recent:
                ip = e['ip']
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)
                if e['lat'] is None or e['lon'] is None:
                    continue
                map_points.append({
                    'lat': e['lat'],
                    'lon': e['lon'],
                    'timestamp': e['timestamp'].strftime('%H:%M:%S'),
                    'campus': e['campus'],
                })

    return render(request, 'bits/analytics.html', {
        'form': form,
        'chart_data': chart_data,
        'map_points': map_points,
        'summary': summary,
        'show_map': form.cleaned_data['show_map'] if form.is_valid() else False,
    })



SUBSCRIPTIONS_FILE = os.path.join(settings.LOG_DIR, 'subscriptions.json')

if os.path.exists(SUBSCRIPTIONS_FILE):
    with open(SUBSCRIPTIONS_FILE, 'r') as f:
        try:
            subscriptions = json.load(f)
        except json.JSONDecodeError:
            subscriptions = []
else:
    subscriptions = []


LOGFILE = os.path.join(settings.LOG_DIR, 'request_logs.log')


### THIS IS WHERE THE REAL SHIT STARTS ###

def isbits(email):
    return email.endswith('bits-pilani.ac.in')

def extract_images_from_request(request):
    existing_images = []
    uploaded_images = []

    print("\n--- DEBUG: POST KEYS ---")
    for key in request.POST:
        print(f"POST key: {key} -> {request.POST.get(key)}")

    print("\n--- DEBUG: FILES KEYS ---")
    for key in request.FILES:
        print(f"FILES key: {key} -> {request.FILES.get(key).name}")

    existing_pattern = re.compile(r'^existingImages\[(\d+)\]\[image\]$')
    for key in request.POST:
        match = existing_pattern.match(key)
        if match:
            idx = int(match.group(1))
            image_data = request.POST.get(key)
            index_key = f"existingImages[{idx}][index]"
            index_value = request.POST.get(index_key, idx)
            print(f"Matched existing image: idx={idx}, image={image_data}, index_key={index_key}")
            existing_images.append({
                'index': int(index_value),
                'image': image_data
            })

    upload_pattern = re.compile(r'^images\[(\d+)\]\[image\]$')
    for key in request.FILES:
        print(f"Checking FILE key for pattern match: {key}")
        match = upload_pattern.match(key)
        if match:
            idx = int(match.group(1))
            image_file = request.FILES.get(key)
            index_key = f"images[{idx}][index]"
            index_value = request.POST.get(index_key, idx)
            print(f"Matched upload: idx={idx}, image={image_file.name}, index_key={index_key}")
            uploaded_images.append({
                'index': int(index_value),
                'image': image_file
            })
        else:
            print(f"WARNING: FILE key '{key}' did NOT match expected pattern")

    print(f"\n--- Extracted {len(existing_images)} existing images ---")
    for img in existing_images:
        print(f"Existing -> index: {img['index']}, image: {img['image']}")

    print(f"\n--- Extracted {len(uploaded_images)} uploaded images ---")
    for img in uploaded_images:
        print(f"Uploaded -> index: {img['index']}, filename: {img['image'].name}")

    existing_images.sort(key=lambda x: x['index'])
    uploaded_images.sort(key=lambda x: x['index'])

    return existing_images, uploaded_images
from django.core.files.uploadedfile import UploadedFile

@ensure_csrf_cookie
def api_items(request):
    start = time.time()
    email = request.session.get('email')
    person = Person.objects.filter(email=email).first()
    if not person:
        print("ACCESS DENIED")
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    if request.method == "GET":
        if person.campus:
            campus_param = request.GET.get('c', person.campus)
        else:
            campus_param = request.GET.get('c', 'ALL')
        page = request.GET.get('p', 1)
        category = request.GET.get('cat', '')
        sort_method = request.GET.get('s', 0)
        query = request.GET.get('q', '')

        if campus_param == "OTH":
            campus_param = "ALL"
        
        campus_param = campus_param.upper()

        cache_params = f"{campus_param}_{category}_{sort_method}_{query}"
        cache_hash = hashlib.md5(cache_params.encode()).hexdigest()
        cache_key_items = f"items_cache_{cache_hash}"
        cache_key_counts = f"category_counts_{cache_hash}"
        
        cached_items = cache.get(cache_key_items)
        cached_counts = cache.get(cache_key_counts)


        print(f"Campus param: {campus_param}")
        
        if cached_items is not None and cached_counts is not None:
            sorted_items = cached_items
            category_counts = cached_counts
            print(f"Cache HIT for: {cache_params}")
        else:
            print(f"Cache MISS for: {cache_params}")
            
            items_query = Item.objects.select_related(
                'seller', 'category', 'hostel'
            ).prefetch_related(
                Prefetch('images', queryset=Image.objects.order_by('display_order'))
            )

            if campus_param and campus_param != 'ALL':
                print("FILTERING!!")
                items_query = items_query.filter(seller__campus=campus_param)

            if query:
                items_query = items_query.filter(
                    Q(name__icontains=query) |
                    Q(hostel__name__icontains=query) |
                    Q(description__icontains=query) |
                    Q(category__name__icontains=query) |
                    Q(seller__name__icontains=query)
                )

            base_query = items_query
            if category:
                items_query = items_query.filter(category__id=category)

            category_counts = dict(
                base_query.values('category').annotate(
                    count=Count('id')
                ).values_list('category', 'count')
            )

            sorted_items = helper.items_sort(items_query, sort_method)
            
            cache.set(cache_key_items, sorted_items, 300)
            cache.set(cache_key_counts, category_counts, 300)

        items_per_page = 20
        paginator = Paginator(sorted_items, items_per_page)

        try:
            paginated_items = paginator.page(page)
        except PageNotAnInteger:
            paginated_items = paginator.page(1)
        except EmptyPage:
            paginated_items = paginator.page(paginator.num_pages)

        data = []
        for item in paginated_items:
            images = list(item.images.all())
            first_image = images[0] if images else None
            image_url = request.build_absolute_uri(first_image.image.url) if first_image else ""

            data.append({
                "id": item.id,
                "firstimage": image_url,
                "title": item.name,
                "price": item.price,
                "date": item.updated_at.isoformat(),
                "hostel": item.hostel.name,
                "contact": item.whatsapp,
                "is_sold": item.is_sold,
                "campus": item.seller.campus
            })
        print(time.time()-start)
        return JsonResponse({
            "status": "ok",
            "total_items": paginator.count,
            "total_items_cat": category_counts,
            "items": data,
        })

    elif request.method == "POST":
        if not isbits(email):
            return JsonResponse({"status": "error", "error": "Unauthorized"}, status=401)
        name = request.POST.get("itemName")
        description = request.POST.get('description', '')
        price = request.POST.get('itemPrice')
        category_id = request.POST.get('category')
        phone = request.POST.get('contactNumber')
        hostel_name = request.POST.get('sellerHostel')
        _, images = extract_images_from_request(request)

        if not all([person, name, price, category_id, phone, hostel_name, images]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        try:
            category = Category.objects.get(id=int(category_id))
            hostel = Hostel.objects.get(name=hostel_name) if hostel_name else person.hostel
        except Category.DoesNotExist:
            return JsonResponse({"error": "Invalid category"}, status=400)
        except Hostel.DoesNotExist:
            return JsonResponse({"error": "Invalid hostel"}, status=400)

        person.phone = phone
        person.hostel = hostel
        person.save()

        item = Item.objects.create(
            name=name,
            description=description,
            price=float(price),
            seller=person,
            category=category,
            hostel=hostel,
            phone=phone
        )
        for idx, image_dict in enumerate(images):
            try:
                image_file = image_dict.get('image')
                if not image_file:
                    print(f"[SKIP] No image at index {idx}")
                    continue

                print(f"[DEBUG] Index: {idx}")
                print(f"[DEBUG] type(image_file): {type(image_file)}")
                print(f"[DEBUG] image_file.name: {getattr(image_file, 'name', 'NO NAME')}")
                print(f"[DEBUG] image_file.size: {getattr(image_file, 'size', 'NO SIZE')}")

                assert isinstance(image_file, UploadedFile), f"[ERROR] image_file is not an UploadedFile, got: {type(image_file)}"

                print(f"[TRY SAVE] Saving image: {image_file.name}")
                img = Image(item=item, display_order=idx)
                img.image.save(image_file.name, image_file, save=True)

                print(f"[SAVED] DB OK | path: {img.image.name}")
                print(f"[EXISTS ON DISK?] {os.path.exists(img.image.path)} | path: {img.image.path}")

            except Exception as e:
                print(f"[ERROR] Exception while saving image at index {idx}: {e}")


        try:
            cache.clear()
            print("Cache cleared due to new item creation")
        except Exception as e:
            print(f"Error clearing cache: {e}")

        first_image = item.images.first()
        image_url = first_image.image.url if first_image else ""
        return JsonResponse({
            "id": item.id,
            "itemName": item.name,
            "itemImage": request.build_absolute_uri(image_url),
            "itemPrice": int(item.price),
            "sellerName": item.seller.name,
            "sellerHostel": item.hostel.name,
            "dateAdded": item.added_at.isoformat(),
            "contactNumber": item.phone or item.seller.phone,
            "category": item.category.name,
            "campus": item.seller.campus,
            "sellerEmail": item.seller.email,
            "description": item.description,
            "issold": item.is_sold,
        }, status=201)

    return JsonResponse({"status": "error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_categories(request):
    email = request.session.get('email')
    person = Person.objects.filter(email=email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    if request.method == "GET":
        cats = Category.objects.all()
        data = []
        for cat in cats:
            data.append({
                "id": cat.id,
                "name": cat.name
            })

        return JsonResponse({"status":"ok", "data":data})
    return JsonResponse({"status": "error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_authreceiver(request):
    if request.method == "POST":
        data = json.loads(request.body)
        email = data.get('email')
        name = data.get('name')
        person = Person.objects.filter(email = email).first()
        if not person:
            person = Person.objects.create(name = name, email = email)
        request.session["email"] = email
        resp = JsonResponse({"status": "ok", "campus": person.campus})
        resp.set_cookie(get_token(request))
        request.session["email"] = email
        return resp
    else:
        if not request.session.session_key:
            request.session.create()
        email = request.session.get("email")
        person = Person.objects.filter(email=email).first()
        if person:
            response = JsonResponse({"status": "ok", "campus": person.campus, "name": person.name})
        response = JsonResponse({"info": "No POST data processed."})

        csrf_token = get_token(request)
        response.set_cookie(
            key='csrftoken',
            value=csrf_token,
            max_age=60 * 60 * 24 * 7,
            httponly=False,
            secure=True,
            samesite='None',
            path='/'
        )

        response.set_cookie(
            key='sessionid',
            value=request.session.session_key,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            secure=True,
            samesite='None',
            path='/'
        )

        return response

@ensure_csrf_cookie
def api_hostels(request):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    campus = person.campus

    if request.method == "GET":
        hostels = Hostel.objects.filter(campus=campus).values('name')
        return JsonResponse(list(hostels), safe=False)

    return JsonResponse({"status": "error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_misc(request):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    campus = person.campus
    if request.method == "GET":
        method = request.GET.get("id")
        if int(method) == 1:
            phone = person.phone or None
            hostel = person.hostel or None
            return JsonResponse({
                "phone": phone,
                "hostel": "" if not hostel else hostel.name
            })
        return JsonResponse({"status": "error", "error": "Invalid id"}, status=400)
    return JsonResponse({"status": "error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_specificitem(request, id):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    item = Item.objects.filter(id = int(id)).first()
    if not item:
        return JsonResponse({"status": "error", "error": "Item not found"}, status=404)

    if request.method == "GET":
        images = item.images.all()
        image_urls = [request.build_absolute_uri(img.image.url) for img in images]
        similar_items = (
            item.category.items
            .filter(seller__campus=item.seller.campus)
            .exclude(id=item.id)
            .order_by('?')
        )[0:8]
        similar_items = helper.items_sort(similar_items)
        data = []
        for i in similar_items:
            first_image = i.images.first()
            image_url = request.build_absolute_uri(first_image.image.url) if first_image else ""
            data.append({
                "id": i.id,
                "firstimage": image_url,
                "title": i.name,
                "price": i.price,
                "campus": i.seller.campus,
                "date": i.updated_at.isoformat(),
                "hostel": i.hostel.name,
                "contact": i.whatsapp,
            })

        return JsonResponse({
            "status": "ok",
            "details": {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "campus": item.seller.campus,
                "price": float(item.price),
                "seller": {
                    "name": item.seller.name,
                    "email": item.seller.email,
                },
                "category": item.category.name if item.category else None,
                "hostel": item.hostel.name if item.hostel else None,
                "phone": item.phone,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "images": image_urls,
            },
            "similar_items": data
        }, status=200)

    elif request.method == "POST":
        name = request.POST.get('itemName')
        description = request.POST.get('description', '')
        price = request.POST.get('itemPrice')
        category_id = request.POST.get('category')
        phone = request.POST.get('contactNumber')
        hostel_name = request.POST.get('sellerHostel')
        existing_images, new_images = extract_images_from_request(request)

        if name:
            item.name = name

        if description:
            item.description = description

        if price:
            item.price = float(price)

        if category_id:
            category = Category.objects.filter(id = category_id).first()
            if not category:
                return JsonResponse({"status":"error", "error":"Invalid Category ID"}, status = 405)
            item.category = category

        if phone:
            item.phone = phone
            person.phone = phone

        if hostel_name:
            hostel = Hostel.objects.filter(name = hostel_name).first()
            if not hostel:
                return JsonResponse({"status":"error", "error":"Invalid Hostel name"}, status = 405)
            item.hostel = hostel
            person.hostel = hostel

        if new_images or existing_images:
            combined = []

            for img in existing_images:
                rel = helper.get_image_name(img['image'])
                if rel:
                    combined.append({'type': 'existing', 'path': rel})

            for img in new_images:
                combined.append({'type': 'new', 'file': img['image']})

            keep_ids = []

            for idx, info in enumerate(combined):
                if info['type'] == 'existing':
                    existing_obj = item.images.filter(image=info['path']).first()
                    if existing_obj:
                        existing_obj.display_order = idx
                        existing_obj.save()
                        keep_ids.append(existing_obj.id)
                else:
                    f = info['file']
                    new_obj = Image(item=item, display_order=idx)
                    new_obj.image.save(f.name, f, save=True)
                    keep_ids.append(new_obj.id)

            item.images.exclude(id__in=keep_ids).delete()

        person.save()
        item.repost()

        first_image = item.images.first()
        image_url = request.build_absolute_uri(first_image.image.url) if first_image else ""

        return JsonResponse({
            "status":"ok", 
            "id": item.id,
            "firstimage": image_url,
            "title": item.name,
            "price": item.price,
            "date": item.updated_at.isoformat(),
            "hostel": item.hostel.name,
            "contact": item.whatsapp,
        })
    return JsonResponse({"status": "error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_feedback(request):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    if request.method == "POST":
        try:
            description = request.POST.get('description', '')
            images = request.FILES.getlist('images')
            feedback = Feedback.objects.create()
            feedback.description = description
            feedback.save()
            for image in images:
                FeedbackImage.objects.create(feedback=feedback, image=image)
            return JsonResponse({"status": "ok"})
        except Exception as e:
            return JsonResponse({"status":"ok", "error": str(e)}, status=400)
    else:
        return JsonResponse({"status":"error", "error": "Invalid method"}, status=405)

@ensure_csrf_cookie
def api_mylisting(request):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    if request.method == "GET":
        items = helper.items_sort(person.items.all())
        data = []
        for item in items:
            first_image = item.images.first()
            image_url = request.build_absolute_uri(first_image.image.url) if first_image else ""
            data.append({
                "id": item.id,
                "firstimage": image_url,
                "campus": item.seller.campus,
                "title": item.name,
                "price": item.price,
                "issold": item.is_sold,
                "date": item.updated_at.isoformat(),
                "hostel": item.hostel.name,
                "contact": item.whatsapp,
            })
        return JsonResponse({"status":"ok", "items":data})

    elif request.method == "POST":
        if not isbits(email):
            return JsonResponse({"status": "error", "error": "Unauthorized"}, status=401)
        data = json.loads(request.body)
        method = data.get('method')
        ids = list(map(int, data.get('ids', [])))
        items = Item.objects.filter(id__in = ids)
        if method == "DELETE":
            items.delete()
        elif method == "REPOST":
            for item in items:
                item.repost()
        elif method == "MARK SOLD":
            items.update(is_sold = True)
        elif method == "MARK UNSOLD":
            items.update(is_sold = False)
        else:
            return JsonResponse({"status":"error", "error":"Illegal Method"}, status=405)

        return JsonResponse({"status":"ok", "ids":ids})
    return JsonResponse({"status":"error", "error":"Invalid Method"}, status=405)

@ensure_csrf_cookie
def api_feedback(request):
    email = request.session.get('email')
    person = Person.objects.filter(email = email).first()
    if not person:
        return JsonResponse({"status": "error", "error": "Access Denied!"}, status=403)

    if request.method == "POST":
        try:
            description = request.POST.get('description', '')
            images = request.FILES.getlist('images')
            feedback = Feedback.objects.create()
            feedback.description = description
            feedback.save()
            for image in images:
                FeedbackImage.objects.create(feedback=feedback, image=image)
            return JsonResponse({"status": "ok"})
        except Exception as e:
            return JsonResponse({"status":"ok", "error": str(e)}, status=400)
    else:
        return JsonResponse({"status":"error", "error": "Invalid method"}, status=405)
from django.http import JsonResponse

def csrf_failure_debug(request, reason=""):
    print("CSRF FAILURE DETECTED")
    print("Reason:", reason)
    print("Method:", request.method)
    print("Path:", request.path)
    print("Headers:", dict(request.headers))
    print("POST Data:", dict(request.POST))
    return JsonResponse({
        "error": "CSRF verification failed",
        "reason": reason
    }, status=403)
