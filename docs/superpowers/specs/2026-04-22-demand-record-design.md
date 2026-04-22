# 需求周报数据同步设计文档

---

## 1. 项目概述

### 1.1 业务背景

本系统服务于**上海迪士尼度假区（SHDR）灌溉团队**接收其他部门需求的工作管理。当前团队使用Excel周报记录各部门提出的灌溉相关需求，包括浇水协调、项目配合、维护维修等。需要将这些数据迁移至Django数据库，实现数字化管理和网页报表生成。

### 1.2 数据来源

- Excel文件：`002 需求周报.xlsx`（2026年Q1季度数据）
- Sheet: 26Q1（57行 x 253列）
- 数据日期范围：2025-12-31 至 2026-05-05

### 1.3 系统目标

- 一次性迁移Excel历史数据到Django数据库
- 后续通过Web/App填报，数据存入Django
- 支持网页端生成按天/周/月/年的统计报表
- 支持按区域、类别、部门四个维度统计

---

## 2. 数据结构分析

### 2.1 Excel结构概览

| 维度 | 说明 |
|------|------|
| 行（Row） | 类别/区域标签：停水停电、项目施工、30+个灌溉区域、工作类别等 |
| 列（Column） | 日期：每2列一组（日期列+备注列），覆盖整个季度 |
| 单元格内容 | 需求描述，包含时间段（如"2300-600"、"巡道 400-700"） |

### 2.2 行类别分类

**全局事件类（2行）：**
- Row 3: 停水停电
- Row 4: 项目施工

**区域类（30行）- 映射到Zone：**
- 01西门、02东门、03TL、03TL水池、05FL408、06FL406、07AI&ME、08TC、09Garden、10H2、11H1、12RDE、13PTC、14GPL
- 35-2探索路、35-5北泵站、36北环路、37-3西环路、37-6西泵站、38-3西南环、38-3西喷泉、38-4西南环、38-6高架边、39-03南环路、39-10星光道、39-11灵感街、40-3奇妙路、43-1东大湖、44-3南大湖、45-2西大湖
- Sitewalk1、Sitewalk2

**工作类别类（17行）- 新建DemandCategory：**
- Row 38: 项目配合
- Row 39: 配合走场
- Row 40: Improvement
- Row 41: Learning
- Row 42-43: 询价1、询价2
- Row 44-45: 养护维修1、养护维修2
- Row 46: 项目维修
- Row 47: 咨询
- Row 48: 设计
- Row 49: 团队
- Row 51: 安全
- Row 52: Meeting
- Row 53: Visit
- Row 54: 奖惩

### 2.3 单元格内容格式

典型内容示例：
- `"2300-600"` - 时间段（夜间23:00至次日6:00）
- `"巡道 400-700"` - 工作内容+时间段
- `"低温 -5 度 2处铜管冻裂"` - 天气+事件描述
- `"全场浇"` - 工作范围描述
- `"MA 2230-230"` - 区域代号+时间段

时间段解析规则：
- 格式：`HHMM-HHMM` 或 `HH:MM-HH:MM`
- 跨天处理：如 `2300-600` 表示23:00至次日06:00

---

## 3. 数据模型设计

### 3.1 新建模型：DemandCategory（需求类别）

```python
class DemandCategory(models.Model):
    """需求类别 - 区别于工单的WorkCategory"""
    
    CATEGORY_TYPE_CHOICES = [
        ('global_event', '全局事件'),
        ('zone_demand', '区域需求'),
        ('work_category', '工作类别'),
    ]
    
    name = models.CharField('名称', max_length=100)
    code = models.CharField('编号', max_length=50, unique=True)
    category_type = models.CharField('类别类型', max_length=20, choices=CATEGORY_TYPE_CHOICES)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'code']
        verbose_name = '需求类别'
        verbose_name_plural = '需求类别'
```

### 3.2 新建模型：DemandDepartment（需求部门）

```python
class DemandDepartment(models.Model):
    """提出需求的部门"""
    
    name = models.CharField('部门名称', max_length=50)
    code = models.CharField('部门编号', max_length=20, unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['order', 'code']
        verbose_name = '需求部门'
        verbose_name_plural = '需求部门'
```

### 3.3 新建模型：DemandRecord（需求记录）

```python
class DemandRecord(models.Model):
    """需求记录 - 其他部门提出的灌溉相关需求"""
    
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_INFO_NEEDED = 'info_needed'
    
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, '已提交'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
        (STATUS_IN_PROGRESS, '进行中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_INFO_NEEDED, '需补充信息'),
    ]
    
    # 基本信息
    date = models.DateField('需求日期', db_index=True)
    content = models.TextField('需求内容/备注')
    original_text = models.TextField('原始文本', blank=True, help_text='Excel原始单元格内容')
    
    # 需求方信息
    demand_department = models.ForeignKey(
        DemandDepartment, on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='demand_records',
        verbose_name='提出部门'
    )
    demand_department_text = models.CharField('提出部门(文本)', max_length=50, blank=True)
    demand_contact = models.CharField('联系人', max_length=100, blank=True)
    
    # 区域信息
    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='demand_records',
        verbose_name='关联区域'
    )
    zone_text = models.CharField('区域(文本)', max_length=100, blank=True, help_text='Excel行标签')
    
    # 全局事件标记
    is_global_event = models.BooleanField('全局事件', default=False)
    affected_zones = models.ManyToManyField(
        Zone, blank=True, related_name='affected_by_demands',
        verbose_name='影响区域'
    )
    
    # 类别信息
    category = models.ForeignKey(
        DemandCategory, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='demand_records',
        verbose_name='需求类别'
    )
    category_text = models.CharField('类别(文本)', max_length=100, blank=True)
    
    # 时间段（解析后的结构化数据）
    start_time = models.TimeField('开始时间', null=True, blank=True)
    end_time = models.TimeField('结束时间', null=True, blank=True)
    crosses_midnight = models.BooleanField('跨天', default=False, help_text='结束时间是否跨过午夜')
    time_parsed = models.BooleanField('时间已解析', default=False)
    
    # 审批流程
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_APPROVED)
    submitter = models.ForeignKey(
        Worker, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='submitted_demands',
        verbose_name='提交人'
    )
    approver = models.ForeignKey(
        Worker, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_demands',
        verbose_name='审批人'
    )
    processed_at = models.DateTimeField('处理时间', null=True, blank=True)
    status_notes = models.TextField('审批备注', blank=True)
    
    # 关联工单
    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='linked_demand',
        verbose_name='关联工单'
    )
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['date', 'zone']),
            models.Index(fields=['date', 'category']),
        ]
        verbose_name = '需求记录'
        verbose_name_plural = '需求记录'
    
    def __str__(self):
        return f"{self.date} | {self.zone_text or '全局'} | {self.content[:30]}"
```

---

## 4. Excel数据迁移方案

### 4.1 迁移脚本逻辑

```
1. 解析Excel文件 '002 需求周报.xlsx'
2. 遍历每列（日期列）
   - 获取日期值（Row 2）
3. 遍历每行（类别/区域）
   - 跳过空行、汇总行
   - 识别行类别（全局事件/区域/工作类别）
4. 读取单元格内容
   - 解析时间段（如有）
   - 存储原始文本
5. 创建DemandRecord记录
   - 设置date, content, zone_text, category_text
   - 设置start_time, end_time（解析成功时）
   - 默认status='approved'（历史数据）
6. 统计导入数量，验证数据完整性
```

### 4.2 行类别识别规则

| 行号 | 标签 | 类别类型 | 处理方式 |
|------|------|---------|---------|
| 3 | 停水停电 | global_event | is_global_event=True |
| 4 | 项目施工 | global_event | is_global_event=True |
| 6-37 | 区域名 | zone_demand | 关联Zone（如有匹配） |
| 38-54 | 工作类别 | work_category | 关联DemandCategory |

### 4.3 时间段解析规则

```python
def parse_time_segment(text):
    """
    解析时间段，格式如：
    - "2300-600" → 23:00, 06:00 (跨天)
    - "400-700" → 04:00, 07:00
    - "巡道 400-700" → 提取时间段 + 内容
    """
    import re
    pattern = r'(\d{1,4})[-~](\d{1,4})'
    match = re.search(pattern, text)
    if not match:
        return None, None, False, text
    
    start_str, end_str = match.groups()
    
    # 解析时间
    start_hour = int(start_str[:len(start_str)-2] or '0')
    start_min = int(start_str[-2:] or '0')
    end_hour = int(end_str[:len(end_str)-2] or '0')
    end_min = int(end_str[-2:] or '0')
    
    start_time = f"{start_hour:02d}:{start_min:02d}"
    end_time = f"{end_hour:02d}:{end_min:02d}"
    
    # 判断跨天
    crosses_midnight = start_hour >= 12 and end_hour < 12
    
    # 提取剩余内容
    remaining = text.replace(match.group(), '').strip()
    
    return start_time, end_time, crosses_midnight, remaining
```

---

## 5. 统计报表需求

### 5.1 统计维度

| 维度 | 说明 | 实现方式 |
|------|------|---------|
| 时间统计 | 按周/月/年汇总需求数量和时长 | date字段分组聚合 |
| 区域统计 | 按Zone统计需求频次和工作量 | zone字段分组聚合 |
| 类别统计 | 按DemandCategory统计 | category字段分组聚合 |
| 部门统计 | 按提出部门统计需求量 | demand_department字段分组聚合 |

### 5.2 报表API设计

```
/api/demand-stats/
  ?start_date=2026-01-01
  &end_date=2026-03-31
  &group_by=week|month|year
  &dimension=zone|category|department

返回格式：
{
  "groups": [
    {"label": "2026-W01", "count": 45, "total_hours": 120},
    ...
  ],
  "breakdown": {
    "zone": [...],
    "category": [...],
    "department": [...]
  }
}
```

---

## 6. 实施步骤

### Step 1: 创建数据模型
- 在 `models.py` 中添加 `DemandCategory`、`DemandDepartment`、`DemandRecord`
- 运行 `makemigrations` 和 `migrate`

### Step 2: 创建字典数据
- 创建Seed脚本，导入DemandCategory初始数据（17个类别）
- 创建Seed脚本，导入DemandDepartment初始数据（FES/FAM/ENT/其他）
- 可选：根据Excel行标签创建缺失的Zone记录

### Step 3: 编写迁移脚本
- 创建 `import_demand_records.py` 脚本
- 解析Excel，创建DemandRecord记录
- 统计导入数量，输出验证报告

### Step 4: 验证数据
- 检查导入记录数与Excel非空单元格数匹配
- 检查时间段解析成功率
- 检查Zone关联率

### Step 5: 添加Admin管理界面
- 注册 `DemandCategory`、`DemandDepartment`、`DemandRecord` 到 admin.py
- 添加筛选、搜索功能

---

## 7. 数据规模估算

| 指标 | 估算值 |
|------|--------|
| Excel总列数 | ~126（日期列） |
| Excel总行数 | ~50（有效数据行） |
| 总单元格数 | ~6,300 |
| 非空单元格预估 | ~500-800条需求记录 |
| 时间段解析成功率预估 | 60-70% |
| Zone匹配率预估 | 80-90%（根据现有Zone表） |

---

*设计文档完成，准备进入实施阶段。*