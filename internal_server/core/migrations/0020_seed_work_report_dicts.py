from django.db import migrations


def seed_data(apps, schema_editor):
    Location = apps.get_model('core', 'Location')
    WorkCategory = apps.get_model('core', 'WorkCategory')
    InfoSource = apps.get_model('core', 'InfoSource')
    FaultCategory = apps.get_model('core', 'FaultCategory')
    FaultSubType = apps.get_model('core', 'FaultSubType')

    # --- Locations (28) ---
    locations = [
        ('CCU1', 'CCU1'), ('CCU2', 'CCU2'), ('CCU3', 'CCU3'),
        ('CCU5', 'CCU5'), ('CCU6', 'CCU6'), ('CCU7', 'CCU7'),
        ('CCU8', 'CCU8'), ('CCU9', 'CCU9'), ('CCU10', 'CCU10'),
        ('CCU11', 'CCU11'), ('CCU12', 'CCU12'), ('CCU13', 'CCU13'),
        ('CCU14', 'CCU14'), ('CCU35', 'CCU35'), ('CCU36', 'CCU36'),
        ('CCU37', 'CCU37'), ('CCU38', 'CCU38'), ('CCU39', 'CCU39'),
        ('CCU40', 'CCU40'), ('CCU43', 'CCU43'), ('CCU44', 'CCU44'),
        ('CCU45', 'CCU45'),
        ('WAREHOUSE', '仓库'), ('OTHER', '其它'),
        ('INNER_AREA', '内场重点区域'), ('WTP', '水厂'),
        ('SHENDI', '申迪范围'), ('NURSERY', '苗圃'),
    ]
    for i, (code, name) in enumerate(locations):
        Location.objects.get_or_create(code=code, defaults={'name': name, 'order': i})

    # --- Work Categories (9) ---
    cats = [
        ('ROUTINE', '常规维护'), ('EMERGENCY', '应急维修'),
        ('FAM', 'FAM项目'), ('WDI', 'WDI项目'),
        ('OTHER_PROJ', '其它项目'), ('HORTICULTURE', '园艺项目'),
        ('INNER', '内场重点区域'), ('WAREHOUSE', '仓库整理'),
        ('DRAINAGE', '绿化排水'),
    ]
    for i, (code, name) in enumerate(cats):
        WorkCategory.objects.get_or_create(code=code, defaults={'name': name, 'order': i})

    # --- Info Sources (4) ---
    sources = [
        ('SELF', '自行巡检'), ('CLEANING', '保洁同事报'),
        ('OTHER_DEPT', '其他部门报'), ('LANDSCAPE', '绿化同事报'),
    ]
    for i, (code, name) in enumerate(sources):
        InfoSource.objects.get_or_create(code=code, defaults={'name': name, 'order': i})

    # --- Fault Categories & Sub-Types ---
    fault_data = [
        ('项目配合', 'Project', [
            ('项目配合', 'Project', 'PROJ'),
        ]),
        ('新苗/保湿', 'New Planting', [
            ('新苗/保湿', 'New Planting', 'NEW_PLANT'),
        ]),
        ('控水', 'Pause Watering', [
            ('控水', 'Pause Watering', 'PAUSE_WATER'),
        ]),
        ('系数调整', 'LC Adjust', [
            ('系数调整', 'LC Adjust', 'LC_ADJUST'),
        ]),
        ('喷头', 'Sprinkler', [
            ('喷头盖掉/松/坏', 'Sprinkler Cap Loose/Drop', 'SPR_CAP'),
            ('喷头脱落', 'Sprinkler Drop', 'SPR_DROP'),
            ('喷嘴丢/坏', 'Nozzle Damaged', 'NOZZLE_DMG'),
            ('喷芯掉或坏', 'Internal Damaged/Dropped', 'SPR_INTERNAL'),
            ('喷嘴无机物堵', 'Debris Clogged', 'NOZZLE_DEBRIS'),
            ('喷嘴螺蛳苗堵', 'Shell Clogged', 'NOZZLE_SHELL'),
            ('弹簧丢/伸缩卡', 'Spring Lost/Fail Up-down', 'SPR_SPRING'),
            ('止溢胶圈变形/缺失漏水', 'SAM Seal Ring Leakage', 'SAM_SEAL'),
            ('易坏喷头加套管', 'Add Pop-up Sleeve', 'SPR_SLEEVE'),
            ('养护作业机械损坏喷头', 'Broken by maintenance', 'SPR_MAINT'),
            ('喷头断/掉', 'Sprinkler Broken', 'SPR_BREAK'),
            ('壳体裂/掉', 'Body Crack/Drop', 'SPR_BODY'),
            ('喷头丝口坏', 'Body Inlet Damaged', 'SPR_INLET'),
            ('喷头被埋', 'Buried', 'SPR_BURIED'),
            ('喷头冻坏', '', 'SPR_FREEZE'),
            ('喷嘴不匹配', '', 'NOZZLE_MISMATCH'),
            ('喷嘴角度不对', '', 'NOZZLE_ANGLE'),
        ]),
        ('铰接', 'Swing Joint', [
            ('黑弯头断', 'Black Elbow Broken', 'SJ_ELBOW'),
            ('树根挤压破坏', 'Root Damage', 'SJ_ROOT'),
            ('黑弯头丝坏', 'Thread Damaged', 'SJ_THREAD'),
            ('三通坏', 'Tee Damaged', 'SJ_TEE'),
            ('弯头断在三通里', 'Elbow Broken inside Tee', 'SJ_IN_TEE'),
        ]),
        ('喷头调整', 'Sprinkler Adjustment', [
            ('加高', 'Height Increase', 'ADJ_UP'),
            ('降低', 'Height Decrease', 'ADJ_DOWN'),
            ('加装喷头', 'Add Sprinkler', 'ADJ_ADD'),
            ('改喷头', 'Change Nozzle or Sprinkler', 'ADJ_CHANGE'),
            ('移位/歪斜', 'Relocation', 'ADJ_MOVE'),
            ('主动埋/拆/堵喷头', 'Cap Head', 'ADJ_CAP'),
            ('恢复锁闭的喷嘴', 'Resume Watering', 'ADJ_RESUME'),
            ('堵/调喷嘴/取消喷头', 'Plug/Adjust Arc/Cancel', 'ADJ_PLUG'),
        ]),
        ('喷头立管/加长杆', 'Riser/Extension', [
            ('断', 'Broken', 'RISER_BREAK'),
            ('脱落', 'Dropped', 'RISER_DROP'),
        ]),
        ('滴灌无水/漏水', 'Drip Fault', [
            ('滴灌无水/漏水', 'Drip Fault', 'DRIP'),
        ]),
        ('主管隔离阀', 'Isolate Valve', [
            ('卡死', 'Stuck', 'ISO_STUCK'),
            ('关不了', 'ON/OFF Check', 'ISO_STUCK_OFF'),
        ]),
        ('电磁阀及阀箱', 'Solenoid Valve & Valve Box', [
            ('调压器未装或坏', 'Pressure Regulator Not in Place', 'SV_PRS'),
            ('调压器堵', 'PRS-Low Pressure/Clog', 'SV_PRS_CLOG'),
            ('蜂巢', 'Bee Net', 'SV_BEE'),
            ('不能开/喷头无法弹起', 'Fail to Turn ON', 'SV_FAIL_ON'),
            ('电磁头烧', 'Solenoid Shorted', 'SV_SHORT'),
            ('电磁阀进垃圾', 'Debris inside Valve', 'SV_DEBRIS'),
            ('电磁头松动/铁芯生锈', 'Solenoid Loose', 'SV_LOOSE'),
            ('电磁阀关不住水', 'Fail to Turn OFF', 'SV_FAIL_OFF'),
            ('流量手柄断', 'Flow Bleed Broken', 'SV_BLEED'),
            ('电磁阀漏水', 'Leakage on Valve', 'SV_LEAK'),
            ('阀体有裂缝', 'Crack', 'SV_CRACK'),
            ('球阀漏水', 'Leakage on Ball Valve', 'SV_BALL'),
            ('活接弯头漏水', 'Leakage on Union Elbow', 'SV_UNION'),
            ('主动关球阀', 'OFF Ball Valve as Required', 'SV_BALL_OFF'),
            ('球阀被关', 'Ball Valve OFFed', 'SV_BALL_OFFED'),
            ('阀箱被埋/提升', 'Valve Box Buried', 'VB_BURIED'),
            ('降低阀门箱', 'Valve Box Lowering', 'VB_LOWER'),
            ('密封/胶垫坏', 'Seal Break', 'VB_SEAL'),
            ('阀箱损坏或丢失', 'Box Damaged or Missed', 'VB_DMG'),
        ]),
        ('CCU', 'CCU', [
            ('控制线不通', 'Control Wire Open', 'CCU_WIRE'),
            ('通讯断', 'Comm Disconnected', 'CCU_COMM'),
            ('假数据', 'Unreasonable Data', 'CCU_DATA'),
        ]),
        ('控制器', 'Satellite Controller', [
            ('可控硅坏/异常输出', 'TRAC Shorted', 'SC_TRAC'),
            ('保险丝烧', 'Fuse Burnt', 'SC_FUSE'),
            ('PC反馈故障', 'PC显示异常/现场正常', 'SC_PC_ABNORM'),
            ('PC显示正常/现场异常', '', 'SC_PC_NORMAL'),
            ('故障灯闪', 'Fault Lit Flashing', 'SC_FAULT'),
            ('通讯故障', 'Comm Fault', 'SC_COMM'),
            ('通讯板故障', 'Comm Board Fault', 'SC_COMM_BOARD'),
            ('非中控', 'Standalone Status', 'SC_STANDALONE'),
            ('撞坏', 'Crashed by Accident', 'SC_CRASH'),
            ('电源断', 'Power OFFed', 'SC_POWER'),
            ('控制柜进水', 'Water Penetration', 'SC_WATER'),
            ('排线故障', 'Ribbon Cable', 'SC_RIBBON'),
            ('液晶屏故障', 'LCD Issue', 'SC_LCD'),
            ('拔线忘了恢复', '', 'SC_WIRE_FORGOT'),
            ('线缆被打地锚损坏', '', 'SC_ANCHOR'),
            ('其它故障', '', 'SC_OTHER'),
        ]),
        ('中控', 'Central Control', [
            ('该浇没浇', 'Should Water but Didn\'t', 'CC_MISS'),
            ('显示没浇实浇', 'Display No/Actually Yes', 'CC_FALSE_NEG'),
            ('CCU掉线', 'CCU Offline', 'CC_OFFLINE'),
            ('反常流量', 'Suspicious Leak', 'CC_LEAK'),
            ('现场查中控反馈故障', 'Site Check Fault CC Reported', 'CC_SITE'),
        ]),
        ('遥控器', 'Remote Controller', [
            ('未知开', 'Turn ON Unknown', 'RC_UNKNOWN'),
            ('继电器或电源或烧保险', 'Relay/Power/Fuse Burnt', 'RC_RELAY'),
            ('掉线', 'OFFline', 'RC_OFFLINE'),
            ('无输出', 'No Output', 'RC_NO_OUT'),
            ('数据线不通', 'Data Cable out of Work', 'RC_DATA'),
            ('App失灵', 'App out of Work', 'RC_APP'),
        ]),
        ('冲洗阀', 'Wash-down', [
            ('卡石子/杂物漏水', 'Leakage by Debris/Stone', 'WD_DEBRIS'),
            ('铜管钥匙破裂', 'Copper Key Cracked', 'WD_COPPER'),
            ('漏水查漏', 'Leakage Unknown', 'WD_LEAK'),
            ('排水堵', 'Fail to Drainage', 'WD_DRAIN'),
            ('更换设施地插', 'Replace Regular WD', 'WD_REPLACE'),
            ('地插短管缺补', '', 'WD_SHORT'),
            ('地插清堵', '', 'WD_CLEAR'),
            ('地插车撞', '', 'WD_CRASH'),
            ('钥匙开裂/丝断', 'Key Cracked', 'WD_KEY'),
            ('铜短管开裂', 'Copper Nipple Cracked', 'WD_NIPPLE'),
            ('活接漏水', '', 'WD_UNION'),
            ('胶圈漏水', '', 'WD_SEAL'),
        ]),
        ('取水阀', 'Quick Coupling Valve', [
            ('漏水', 'Leakage', 'QCV_LEAK'),
            ('钥匙弯头坏', 'Copper Key Elbow Damaged', 'QCV_KEY'),
            ('新安装', 'New Add', 'QCV_NEW'),
            ('移位', 'Relocation', 'QCV_MOVE'),
            ('阀门箱盖子缺失', 'Valve Box Lip Lost', 'QCV_LIP'),
            ('降低阀箱高度', 'Valve Box Adjusting', 'QCV_ADJ'),
        ]),
        ('POC', 'POC', [
            ('主阀被手动关', 'Manual OFFed Master Valve', 'POC_MANUAL'),
            ('主阀不能关', 'Master Valve Fail OFF', 'POC_FAIL_OFF'),
            ('主阀不能开', 'Master Valve Fail ON', 'POC_FAIL_ON'),
            ('小铜管球阀不能开关/漏水', 'Pilot Valve Failed', 'POC_PILOT'),
            ('过滤器滤网堵', 'Y-Strainer Screen Clogged', 'POC_STRAINER'),
            ('主阀滤网堵/丢', 'Master Valve Filter Clogged', 'POC_FILTER'),
            ('防冻排空', 'Freezing Protection', 'POC_FREEZE'),
            ('排气阀漏水', '', 'POC_AIR'),
            ('管件漏水', 'Fitting Leakage', 'POC_FITTING'),
            ('闸阀故障', 'Gate Valve Fault', 'POC_GATE'),
            ('压力表故障', 'Pres. Gauge Fault', 'POC_GAUGE'),
            ('针形阀密封漏', 'Needle Valve Seal Fail', 'POC_NEEDLE'),
        ]),
        ('主管', 'Mainline', [
            ('查漏', 'Leakage Investigation', 'ML_INVEST'),
            ('管道漏水', 'Mainline Leakage', 'ML_LEAK'),
            ('管件漏水', 'Fitting Leakage', 'ML_FITTING'),
            ('改管道', 'Mainline Relocation', 'ML_RELOCATE'),
            ('阀箱加高或降低', 'Valve Box Adjustment', 'ML_VB_ADJ'),
            ('修管道', 'Mainline Repair', 'ML_REPAIR'),
        ]),
        ('角阀', 'Angle Valve', [
            ('角阀坏', 'Fail On/Off', 'AV_FAIL'),
            ('沉降漏水', 'Settlement Leak', 'AV_SETTLE'),
        ]),
        ('支管', 'Lateral', [
            ('改管道', 'Lateral Relocation', 'LAT_RELOCATE'),
            ('修管道', 'Lateral Repair', 'LAT_REPAIR'),
            ('修接头', 'Fitting Leakage', 'LAT_FITTING'),
            ('脱胶', 'Poor Glue Connection', 'LAT_GLUE'),
            ('查漏', 'Leakage Investigation', 'LAT_INVEST'),
            ('其它施工破坏', 'Damaged by Construction', 'LAT_CONSTRUCT'),
        ]),
        ('雨量桶', 'Site Rain Gauge', [
            ('无信号', 'No Signal Input', 'RG_NOSIG'),
            ('电脑异常/现场正常', 'Abnormal Signal', 'RG_ABNORM'),
            ('电脑异常/现场异常', '', 'RG_BOTH'),
            ('有杂物', 'Debris Inside', 'RG_DEBRIS'),
        ]),
        ('流量计', 'Flow Sensor', [
            ('脉冲发生器故障', 'Pulse Transmitter Fault', 'FS_PULSE'),
            ('流量计故障', 'Flow Sensor Fault', 'FS_FAULT'),
            ('流量计更换', 'Replace FS', 'FS_REPLACE'),
            ('解码器故障', 'Decoder Fault', 'FS_DECODER'),
            ('数据异常', 'Unreasonable Data', 'FS_DATA'),
        ]),
        ('控制线', 'Control Wire', [
            ('断路', 'Discontinue', 'CW_BREAK'),
            ('接地', 'Grounding Fault', 'CW_GROUND'),
            ('拔控制线停水', 'Disconnect Wire Stop-water', 'CW_DISCONNECT'),
            ('地锚打坏线', '', 'CW_ANCHOR'),
        ]),
        ('临时停水', 'Temp OFF Watering', [
            ('临时停水', 'OFF Watering Temp', 'TEMP_OFF'),
        ]),
        ('临时补水', 'Temp Watering by Remote', [
            ('换/补植物', 'New Plant/Seeding', 'TW_NEW'),
            ('施肥', 'Fertilizer Application', 'TW_FERT'),
            ('打药', 'Chemical Application', 'TW_CHEM'),
            ('地锚打坏主管/支管', 'Duckbill Damage Mainline', 'TW_ANCHOR'),
        ]),
        ('其他', 'Other', [
            ('其他', 'Other', 'OTHER'),
        ]),
        ('车撞破坏', 'Traffic Damage', [
            ('车撞破坏维修', 'Traffic Damage', 'TRAFFIC'),
        ]),
        ('施工破坏', 'Damage by Site Construction', [
            ('施工破坏', 'Damage by Site Job', 'CONSTRUCT'),
        ]),
        ('现场跟进', 'Site Support', [
            ('现场跟进', 'Site Support', 'SITE_SUPPORT'),
        ]),
        ('上游停水', 'No Water', [
            ('上游停水', 'Stop Water Supplying Upstream', 'UPSTREAM'),
        ]),
        ('现场水分', 'Soil Moisture Status', [
            ('和绿化一起看现场植物长势', 'Plant Status Check with Lnd', 'SM_TOGETHER'),
            ('灌溉组独立查看现场植物长势', 'Plant Status Check by Irrigation', 'SM_ALONE'),
            ('积水/排水不够', 'Flood/Poor Drainage', 'SM_FLOOD'),
            ('土壤水分偏湿', 'Soil Moisture Too High', 'SM_WET'),
            ('土壤水分偏干', 'Soil Moisture Too Low', 'SM_DRY'),
        ]),
        ('其他辅助分类', 'Other Auxiliary', [
            ('材料库存', '', 'AUX_STOCK'),
            ('转出工单', '', 'AUX_TRANSFER'),
            ('树根损坏', '', 'AUX_ROOT'),
            ('滴灌损坏', '', 'AUX_DRIP'),
        ]),
    ]

    sub_type_counter = 0
    for cat_idx, (cat_name_zh, cat_name_en, sub_types) in enumerate(fault_data):
        cat, _ = FaultCategory.objects.get_or_create(
            name_zh=cat_name_zh,
            defaults={'name_en': cat_name_en, 'order': cat_idx}
        )
        for sub_name_zh, sub_name_en, sub_code in sub_types:
            FaultSubType.objects.get_or_create(
                code=sub_code,
                defaults={
                    'category': cat,
                    'name_zh': sub_name_zh,
                    'name_en': sub_name_en,
                    'order': sub_type_counter,
                }
            )
            sub_type_counter += 1


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_faultcategory_faultsubtype_infosource_location_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_seed),
    ]
