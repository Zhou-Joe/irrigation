from django import forms
from django.contrib.auth import get_user_model

from .access import visible_locations
from .models import LandscapingAsset, LandscapingSpecies, LandscapingWorkOrder, LandscapingDelivery


class SpeciesForm(forms.ModelForm):
    class Meta:
        model = LandscapingSpecies
        fields = ['code', 'name', 'scientific_name', 'family', 'genus', 'category', 'special', 'identification', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def clean(self):
        data = super().clean()
        if data.get('identification') == 'confirmed' and not data.get('scientific_name'):
            self.add_error('scientific_name', '确认辨识前请填写拉丁学名。')
        return data


class AssetForm(forms.ModelForm):
    class Meta:
        model = LandscapingAsset
        fields = ['code', 'name', 'kind', 'location', 'species', 'description', 'latitude', 'longitude',
                  'measurement_method', 'height_m', 'dbh_cm', 'crown_m', 'area_m2', 'risk', 'next_care_date', 'notes']
        labels = {'location': '所属区域'}
        widgets = {'next_care_date': forms.DateInput(attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 3}),
                   'species': forms.SelectMultiple(attrs={'size': 5})}
        help_texts = {'species': '树木选择一个种类；绿地区块可选择多个。',
                      'latitude': '可先建立档案，待实测后补充坐标。',
                      'measurement_method': '记录实际采集方式；录入坐标不代表通过精度验收。',
                      'risk': '由专业人员评估填写，未评估时保持“未评估”。'}

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        places = visible_locations(team)
        self.fields['location'].queryset = places
        self.fields['location'].label_from_instance = lambda obj: obj.name
        self.fields['species'].queryset = LandscapingSpecies.objects.filter(team=team)

    def clean(self):
        data = super().clean()
        lat, lng = data.get('latitude'), data.get('longitude')
        if (lat is None) != (lng is None):
            self.add_error('latitude', '经纬度需要同时填写或同时留空。')
        if lat is not None and data.get('measurement_method') == 'unmeasured':
            self.add_error('measurement_method', '有坐标时请选择定位来源。')
        if lat is None and data.get('measurement_method') not in (None, 'unmeasured'):
            self.add_error('measurement_method', '请补充坐标，或选择“未测量”。')
        if data.get('kind') == 'tree' and data.get('species') is not None and len(data['species']) > 1:
            self.add_error('species', '一棵树木只关联一个植物种类。')
        return data


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = LandscapingWorkOrder
        fields = ['title', 'kind', 'location', 'assets', 'scheduled_date', 'assignee', 'instructions']
        labels = {'location': '作业区域', 'assignee': '处理人'}
        widgets = {'scheduled_date': forms.DateInput(attrs={'type': 'date'}),
                   'instructions': forms.Textarea(attrs={'rows': 4}), 'assets': forms.SelectMultiple(attrs={'size': 6})}

    def __init__(self, *args, member, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].queryset = visible_locations(member.team)
        self.fields['location'].label_from_instance = lambda obj: obj.name
        self.fields['assets'].queryset = LandscapingAsset.objects.filter(team=member.team)
        self.fields['assignee'].queryset = get_user_model().objects.filter(is_active=True,
            team_memberships__team=member.team, team_memberships__active=True,
            team_memberships__role__in=['field', 'manager']).distinct()
        self.fields['assignee'].label_from_instance = lambda obj: obj.get_full_name() or obj.username
        if member.role != 'manager':
            self.fields.pop('assignee')

    def clean(self):
        data = super().clean()
        if not data.get('location') and not data.get('assets'):
            raise forms.ValidationError('请选择作业区域或关联至少一个树木 / 绿地档案。')
        return data


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = LandscapingDelivery
        fields = ['name', 'supplier', 'kind', 'region', 'expected_date', 'record_count', 'status', 'notes']
        widgets = {'expected_date': forms.DateInput(attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 4})}

    def clean(self):
        data = super().clean()
        if data.get('status') in ('accepted', 'rework') and not data.get('notes', '').strip():
            self.add_error('notes', '请记录验收依据或需要整改的问题。')
        return data
