"""Validated PM writes shared by modal and standalone forms."""
from django import forms

from .models import MaintenancePlan, JobPlanTemplate, Zone


class MaintenancePlanForm(forms.ModelForm):
    frequency_value = forms.IntegerField(min_value=1, label='频率值')
    lead_days = forms.IntegerField(min_value=0, label='提前生成天数')
    start_date = forms.DateField(required=False, label='到期基准日')

    class Meta:
        model = MaintenancePlan
        fields = ['pm_number', 'job_plan', 'crew', 'frequency_value', 'frequency_unit',
                  'start_date', 'lead_days', 'active', 'remark_template', 'patch', 'satellite', 'zones']

    def __init__(self, *args, default_start=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_start = default_start

    def clean(self):
        data = super().clean()
        data['start_date'] = data.get('start_date') or self.default_start
        # Older clients omit this field; omission must not erase asset links.
        if self.instance.pk and 'zones' not in self.data and 'zones_present' not in self.data:
            data['zones'] = self.instance.zones.all()
        jp = data.get('job_plan')
        if jp:
            # Keep only the asset scope used by this Job Plan. Stale hidden
            # fields otherwise mislabel the plan and can validate a later
            # asset-level change against an unrelated association.
            if jp.asset_level != 'zone_group':
                data['zones'] = Zone.objects.none()
            if jp.asset_level != 'sat':
                data['satellite'] = None
            if jp.asset_level != 'ccu':
                data['patch'] = None
        if jp and data.get('active'):
            if jp.asset_level == 'zone_group' and not data.get('zones'):
                self.add_error('zones', 'Zone组计划必须选择关联区域')
            if jp.asset_level == 'ccu' and not data.get('patch'):
                self.add_error('patch', 'CCU计划必须选择关联CCU')
            if jp.asset_level == 'sat' and not data.get('satellite'):
                self.add_error('satellite', 'SAT计划必须选择关联SAT')
            crew = data.get('crew')
            if crew and not crew.active:
                self.add_error('crew', '负责班组已停用，请重新选择')
        return data


class JobPlanForm(forms.ModelForm):
    class Meta:
        model = JobPlanTemplate
        fields = ['name', 'description', 'asset_level', 'active']

    def clean_asset_level(self):
        level = self.cleaned_data['asset_level']
        if self.instance.pk and self.instance.asset_level != level:
            plans = self.instance.plans.filter(active=True)
            key = {'ccu': 'patch', 'sat': 'satellite', 'zone_group': 'zones'}[level]
            if plans.filter(**{key + '__isnull': True}).exists():
                raise forms.ValidationError('已有启用计划缺少此粒度的资产关联，请先调整计划或新建模板')
        return level


def error_message(form):
    return '；'.join(f'{form.fields[name].label if name in form.fields else "计划"}：{message}'
                    for name, messages in form.errors.items() for message in messages)
