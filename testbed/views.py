from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from reservationDashboard.models import Family, Testbed, Device

@login_required
def testbed_overview(request):
    families = Family.objects.prefetch_related(
        'testbeds',
        'testbeds__devices'
    ).all()
    
    context = {
        'families': families,
        'page_title': 'Testbed Overview',
        'page_subtitle': 'Infrastructure Overview'
    }
    return render(request, 'testbed/overview.html', context)

@login_required
def get_family_details(request, family_id):
    try:
        family = Family.objects.get(id=family_id)
        testbeds = Testbed.objects.filter(family=family).prefetch_related('devices')
        
        data = {
            'family_name': family.name,
            'testbeds': [{
                'id': testbed.id,
                'name': testbed.name,
                'total_devices': testbed.total_devices,
                'devices': [{
                    'name': device.name,
                    'mgmt': device.mgmt,
                    'console': device.console,
                    'gateway': device.gateway,
                    'is_eor': device.is_eor,
                    'platform_details': device.platform_details
                } for device in testbed.devices.all()]
            } for testbed in testbeds]
        }
        return JsonResponse(data)
    except Family.DoesNotExist:
        return JsonResponse({'error': 'Family not found'}, status=404)
