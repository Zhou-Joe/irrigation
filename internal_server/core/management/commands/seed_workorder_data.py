"""Seed WorkCategory, FaultCategory, and FaultSubType from workorder.xlsx spec."""

from django.core.management.base import BaseCommand
from core.models import WorkCategory, FaultCategory, FaultSubType


# ── Work Categories (2-level hierarchy from xlsx) ──────────────────────────
WORK_CATEGORIES = [
    # (code, name, parent_code, order)
    ('routine_maint', '常规维护', None, 1),
    ('routine_maint.inspect', '巡检', 'routine_maint', 1),
    ('routine_maint.repair', '维修', 'routine_maint', 2),
    ('routine_maint.priority_area', '内场重点区域', 'routine_maint', 3),
    ('routine_maint.pm', '待开发...继续叠加计划性维护任务(PM工单)', 'routine_maint', 99),

    ('project_support', '项目配合', None, 2),
    ('project_support.fam', 'FAM项目', 'project_support', 1),
    ('project_support.wdi', 'WDI项目', 'project_support', 2),
    ('project_support.horticulture', '园艺项目', 'project_support', 3),
    ('project_support.other', '其他项目', 'project_support', 4),
    ('project_support.phase', '项目阶段', 'project_support', 5),
    ('project_support.followup', '现场跟进', 'project_support', 6),
    ('project_support.modify_pipe', '改支管喷头', 'project_support', 7),
    ('project_support.remove_pipe', '拆支管喷头', 'project_support', 8),
    ('project_support.restore_pipe', '恢复支管喷头', 'project_support', 9),

    ('repair_emergency', '报修应急', None, 3),
    ('warehouse', '仓库整理', None, 4),
    ('warehouse.inventory', '盘点库存', 'warehouse', 1),
    ('warehouse.recycle', '清理回收材料', 'warehouse', 2),
    ('warehouse.process', '材料加工', 'warehouse', 3),
    ('warehouse.cleanup', '仓库清理', 'warehouse', 4),

    ('green_drainage', '绿化排水', None, 5),
    ('green_drainage.tree_anchor', '绿化种树看地锚位置', 'green_drainage', 1),
    ('green_drainage.renovate_mark', '绿化改造标记喷头', 'green_drainage', 2),
    ('green_drainage.seedling_spray', '绿化换苗检查喷洒', 'green_drainage', 3),
    ('green_drainage.seedling_temp', '绿化换苗临时浇水', 'green_drainage', 4),
    ('green_drainage.pesticide_temp', '植保打药临时浇水', 'green_drainage', 5),
    ('green_drainage.aeration_mark', '草坪打孔标记喷头', 'green_drainage', 6),
    ('green_drainage.sand_temp', '草坪铺沙临时浇水', 'green_drainage', 7),
    ('green_drainage.overseed_temp', '草籽交播临时浇水', 'green_drainage', 8),

    ('learning', '学习提升', None, 6),
    ('learning.cad', 'CAD绘图', 'learning', 1),
    ('learning.irrigation_design', '灌溉设计', 'learning', 2),
    ('learning.online', '线上培训', 'learning', 3),
    ('learning.offline', '线下培训', 'learning', 4),

    ('irrigation_dev', '灌溉管理开发', None, 7),
    ('irrigation_dev.color_bind', '色块图绑点', 'irrigation_dev', 1),
    ('irrigation_dev.output_board', '输出板维修', 'irrigation_dev', 2),
    ('irrigation_dev.comm_board', '通讯板维修', 'irrigation_dev', 3),
    ('irrigation_dev.main_board', '主面板维修', 'irrigation_dev', 4),
    ('irrigation_dev.ccu', 'CCU维修', 'irrigation_dev', 5),

    ('team_mgmt', '团队管理', None, 8),
    ('team_mgmt.meeting', '开会交流', 'team_mgmt', 1),

    ('routine_support', '常规配合', None, 9),
    ('routine_support.tree_anchor', '绿化种树看地锚位置', 'routine_support', 1),
    ('routine_support.renovate_mark', '绿化改造标记喷头', 'routine_support', 2),
    ('routine_support.seedling_spray', '绿化换苗检查喷洒', 'routine_support', 3),
    ('routine_support.seedling_temp', '绿化换苗临时浇水', 'routine_support', 4),
    ('routine_support.pesticide_temp', '植保打药临时浇水', 'routine_support', 5),
    ('routine_support.aeration_mark', '草坪打孔标记喷头', 'routine_support', 6),
    ('routine_support.sand_temp', '草坪铺沙临时浇水', 'routine_support', 7),
    ('routine_support.overseed_temp', '草籽交播临时浇水', 'routine_support', 8),
]


# ── Fault Categories + SubTypes (from xlsx rows 25-45) ─────────────────────
FAULT_DATA = [
    # (category_name_zh, category_order, [(subtype_name_zh, subtype_order), ...])
    ('喷头', 1, [
        ('喷头盖掉/松/坏', 1), ('喷头脱落', 2), ('喷嘴丢/坏', 3),
        ('喷芯掉或坏', 4), ('喷嘴无机物堵', 5), ('喷嘴螺蛳苗堵', 6),
        ('弹簧丢/伸缩卡', 7), ('止溢胶圈变形/缺失漏水', 8), ('易坏喷头加套管', 9),
        ('养护作业机械损坏喷头', 10), ('喷头断/掉', 11), ('壳体裂/掉', 12),
        ('喷头丝口坏', 13), ('喷头被埋', 14), ('喷头冻坏', 15),
        ('喷嘴不匹配', 16), ('喷嘴角度不对', 17),
    ]),
    ('铰接', 2, [
        ('黑弯头断', 1), ('树根挤压破坏', 2), ('黑弯头丝坏', 3),
        ('三通坏', 4), ('弯头断在三通里', 5),
    ]),
    ('喷头调整', 3, [
        ('加高', 1), ('降低', 2), ('加装喷头', 3), ('改喷头', 4),
        ('移位/歪斜', 5), ('主动埋/拆/堵喷头', 6), ('恢复锁闭的喷嘴', 7),
        ('堵/调喷嘴/取消喷头', 8),
    ]),
    ('喷头立管', 4, [
        ('断', 1), ('脱落', 2),
    ]),
    ('喷头加长杆', 5, [
        ('断', 1), ('脱落', 2),
    ]),
    ('主管隔离阀', 6, [
        ('卡死', 1), ('关不了', 2), ('调压器未装或坏', 3), ('调压器堵', 4),
        ('蜂巢', 5), ('不能开/喷头无法弹起', 6), ('电磁头烧', 7),
        ('电磁阀进垃圾', 8), ('电磁头松动/铁芯生锈', 9), ('电磁阀关不住水', 10),
        ('流量手柄断', 11), ('电磁阀漏水', 12), ('阀体有裂缝', 13),
        ('球阀漏水', 14), ('活接弯头漏水', 15), ('主动关球阀', 16),
        ('球阀被关', 17), ('阀箱被埋/提升', 18), ('降低阀门箱', 19),
        ('密封/胶垫坏', 20), ('阀箱损坏或丢失', 21), ('控制线不通', 22),
    ]),
    ('电磁阀及阀箱', 7, [
        ('卡死', 1), ('关不了', 2), ('调压器未装或坏', 3), ('调压器堵', 4),
        ('蜂巢', 5), ('不能开/喷头无法弹起', 6), ('电磁头烧', 7),
        ('电磁阀进垃圾', 8), ('电磁头松动/铁芯生锈', 9), ('电磁阀关不住水', 10),
        ('流量手柄断', 11), ('电磁阀漏水', 12), ('阀体有裂缝', 13),
        ('球阀漏水', 14), ('活接弯头漏水', 15), ('主动关球阀', 16),
        ('球阀被关', 17), ('阀箱被埋/提升', 18), ('降低阀门箱', 19),
        ('密封/胶垫坏', 20), ('阀箱损坏或丢失', 21), ('控制线不通', 22),
    ]),
    ('CCU', 8, [
        ('通讯断', 1), ('假数据', 2), ('非中控', 3), ('撞坏', 4),
        ('电源断', 5), ('控制柜进水', 6), ('排线故障', 7), ('液晶屏故障', 8),
        ('拔线忘了恢复', 9), ('线缆被打地锚损坏', 10), ('其它故障', 11),
    ]),
    ('控制器', 9, [
        ('可控硅坏/异常输出', 1), ('保险丝烧', 2), ('PC反馈故障', 3),
        ('CCU掉线', 4), ('PC显示正常现场异常', 5), ('故障灯闪', 6),
        ('通讯故障', 7), ('现场查中控反馈故障', 8),
    ]),
    ('中控', 10, [
        ('该浇没浇', 1), ('显示没浇实浇', 2), ('继电器或电源或烧保险', 3),
        ('掉线', 4), ('反常流量', 5), ('无输出', 6), ('数据线不通', 7),
        ('App失灵', 8),
    ]),
    ('遥控器', 11, [
        ('未知开', 1), ('掉线', 2), ('数据异常', 3),
    ]),
    ('冲洗阀', 12, [
        ('卡石子/杂物漏水', 1), ('漏水查漏', 2), ('铜管钥匙破裂', 3),
        ('钥匙弯头坏', 4), ('排水堵', 5), ('更换设施地插', 6),
        ('地插短管缺补', 7), ('地插清堵', 8), ('地插车撞', 9),
        ('钥匙开裂/丝断', 10), ('铜短管开裂', 11), ('活接漏水', 12),
        ('胶圈漏水', 13),
    ]),
    ('取水阀', 13, [
        ('漏水', 1), ('新安装', 2), ('移位', 3), ('阀门箱盖子缺失', 4),
        ('降低阀箱高度', 5),
    ]),
    ('POC', 14, [
        ('主阀被手动关', 1), ('主阀不能关', 2), ('主阀不能开', 3),
        ('管道漏水', 4), ('管件漏水', 5), ('阀箱加高或降低', 6),
        ('主阀滤网堵/丢', 7), ('防冻排空', 8), ('排气阀漏水', 9),
        ('管件漏水', 10), ('闸阀故障', 11), ('压力表故障', 12),
        ('针形阀密封漏', 13), ('小铜管球阀不能开关/漏水', 14),
        ('过滤器滤网堵', 15),
    ]),
    ('主管', 15, [
        ('查漏', 1), ('角阀坏', 2), ('改管道', 3), ('沉降漏水', 4),
        ('修管道', 5), ('修接头', 6), ('脱胶', 7), ('有杂物', 8),
        ('改管道', 9), ('查漏', 10), ('修管道', 11), ('其它施工破坏', 12),
    ]),
    ('角阀', 16, [
        ('角阀坏', 1),
    ]),
    ('支管', 17, [
        ('无信号', 1), ('电脑异常现场正常', 2), ('电脑异常现场异常', 3),
    ]),
    ('雨量桶', 18, [
        ('脉冲发生器故障', 1), ('流量计故障', 2), ('流量计更换', 3),
        ('解码器故障', 4), ('数据异常', 5),
    ]),
    ('流量计', 19, [
        ('断路', 1), ('接地', 2), ('拔控制线停水', 3), ('地锚打坏线', 4),
    ]),
    ('控制线', 20, [
        ('车撞破坏', 1),
    ]),
    ('车撞破坏', 21, [
        ('车撞破坏', 1),
    ]),
    ('施工破坏', 22, [
        ('施工破坏', 1),
    ]),
    ('现场水分', 23, [
        ('和绿化一起看现场植物长势', 1), ('灌溉组独立查看现场植物长势', 2),
        ('积水/排水不够', 3), ('土壤水分偏湿', 4), ('土壤水分偏干', 5),
    ]),
    ('树根损坏', 24, [
        ('树根损坏', 1),
    ]),
    ('滴灌损坏', 25, [
        ('滴灌损坏', 1),
    ]),
]


class Command(BaseCommand):
    help = 'Seed WorkCategory (2-level), FaultCategory, and FaultSubType from workorder spec'

    def handle(self, *args, **options):
        # ── Work Categories ──
        wc_count = 0
        parent_cache = {}

        for code, name, parent_code, order in WORK_CATEGORIES:
            parent = None
            if parent_code:
                parent = parent_cache.get(parent_code)
                if parent is None:
                    parent = WorkCategory.objects.filter(code=parent_code).first()
                    if parent:
                        parent_cache[parent_code] = parent

            wc, created = WorkCategory.objects.update_or_create(
                code=code,
                defaults={'name': name, 'parent': parent, 'order': order, 'active': True},
            )
            parent_cache[code] = wc
            if created:
                wc_count += 1

        self.stdout.write(self.style.SUCCESS(f'WorkCategory: {wc_count} created, {len(WORK_CATEGORIES) - wc_count} updated'))

        # ── Fault Categories + SubTypes ──
        fc_count = 0
        fs_count = 0

        for cat_name, cat_order, subtypes in FAULT_DATA:
            cat, created = FaultCategory.objects.update_or_create(
                name_zh=cat_name,
                defaults={'order': cat_order, 'active': True},
            )
            if created:
                fc_count += 1

            for idx, (sub_name, sub_order) in enumerate(subtypes):
                sub_code = f"{cat_name}_{idx}"
                sub, created = FaultSubType.objects.update_or_create(
                    code=sub_code,
                    defaults={
                        'category': cat,
                        'name_zh': sub_name,
                        'order': sub_order,
                        'active': True,
                    },
                )
                if created:
                    fs_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'FaultCategory: {fc_count} created | FaultSubType: {fs_count} created'
        ))
