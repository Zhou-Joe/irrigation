"""
Seed script for DemandCategory and DemandDepartment dictionaries.
Run: python3 manage.py shell < seed_demand_dicts.py
or: python3 manage.py shell
    >>> exec(open('seed_demand_dicts.py').read())
"""

from core.models import DemandCategory, DemandDepartment

# ==========================================================================
# DemandCategory - 需求类别（来自Excel行标签）
# ==========================================================================

CATEGORIES = [
    # 全局事件
    {'name': '停水停电', 'code': 'water_power_stop', 'category_type': 'global_event', 'order': 1},
    {'name': '项目施工', 'code': 'project_construction', 'category_type': 'global_event', 'order': 2},

    # 工作类别（来自Excel Row 38-54）
    {'name': '项目配合', 'code': 'project_support', 'category_type': 'work_category', 'order': 10},
    {'name': '配合走场', 'code': 'site_walk', 'category_type': 'work_category', 'order': 11},
    {'name': 'Improvement', 'code': 'improvement', 'category_type': 'work_category', 'order': 12},
    {'name': 'Learning', 'code': 'learning', 'category_type': 'work_category', 'order': 13},
    {'name': '询价1', 'code': 'inquiry_1', 'category_type': 'work_category', 'order': 14},
    {'name': '询价2', 'code': 'inquiry_2', 'category_type': 'work_category', 'order': 15},
    {'name': '养护维修1', 'code': 'maintenance_1', 'category_type': 'work_category', 'order': 16},
    {'name': '养护维修2', 'code': 'maintenance_2', 'category_type': 'work_category', 'order': 17},
    {'name': '项目维修', 'code': 'project_maintenance', 'category_type': 'work_category', 'order': 18},
    {'name': '咨询', 'code': 'consultation', 'category_type': 'work_category', 'order': 19},
    {'name': '设计', 'code': 'design', 'category_type': 'work_category', 'order': 20},
    {'name': '团队', 'code': 'team', 'category_type': 'work_category', 'order': 21},
    {'name': '安全', 'code': 'safety', 'category_type': 'work_category', 'order': 22},
    {'name': 'Meeting', 'code': 'meeting', 'category_type': 'work_category', 'order': 23},
    {'name': 'Visit', 'code': 'visit', 'category_type': 'work_category', 'order': 24},
    {'name': '奖惩', 'code': 'reward_penalty', 'category_type': 'work_category', 'order': 25},

    # 区域需求（通用类别）
    {'name': '区域需求', 'code': 'zone_demand', 'category_type': 'zone_demand', 'order': 100},
]

# ==========================================================================
# DemandDepartment - 需求部门
# ==========================================================================

DEPARTMENTS = [
    {'name': 'FES', 'code': 'FES', 'order': 1},
    {'name': 'FAM', 'code': 'FAM', 'order': 2},
    {'name': 'ENT', 'code': 'ENT', 'order': 3},
    {'name': '其他', 'code': 'OTHER', 'order': 4},
]

# ==========================================================================
# Seed execution
# ==========================================================================

def seed_categories():
    """Seed DemandCategory table."""
    created = 0
    updated = 0
    for data in CATEGORIES:
        obj, is_created = DemandCategory.objects.update_or_create(
            code=data['code'],
            defaults=data
        )
        if is_created:
            created += 1
        else:
            updated += 1
    print(f"DemandCategory: Created {created}, Updated {updated}, Total {DemandCategory.objects.count()}")

def seed_departments():
    """Seed DemandDepartment table."""
    created = 0
    updated = 0
    for data in DEPARTMENTS:
        obj, is_created = DemandDepartment.objects.update_or_create(
            code=data['code'],
            defaults=data
        )
        if is_created:
            created += 1
        else:
            updated += 1
    print(f"DemandDepartment: Created {created}, Updated {updated}, Total {DemandDepartment.objects.count()}")

def run_seed():
    """Run all seed functions."""
    print("Seeding demand dictionaries...")
    seed_categories()
    seed_departments()
    print("Done!")

# Run when executed directly
if __name__ == '__main__':
    run_seed()

# For shell execution
run_seed()