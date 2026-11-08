from django import forms
from .models import Location


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'code', 'kind', 'map_display', 'parent', 'description', 'latitude', 'longitude']
        labels = {'name': '地点名称', 'code': '地点编号（选填）', 'kind': '地点类型', 'parent': '上级地点（选填）',
                  'map_display': '地图显示方式', 'description': '位置说明',
                  'latitude': '纬度（选填）', 'longitude': '经度（选填）'}
        help_texts = {'kind': '图钉的图标和颜色按地点类型区分。',
                      'map_display': '建筑等地点只需一个大致位置，可在下方地图点选，不需要绘制轮廓。未定位的地点仍可用于工单。'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, parents, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['map_display'].required = False
        self.fields['parent'].queryset = parents
        self.fields['parent'].label_from_instance = lambda obj: obj.name
        if self.instance.legacy_zone_id:
            self.fields['latitude'].disabled = True
            self.fields['longitude'].disabled = True

    def clean_map_display(self):
        return self.cleaned_data.get('map_display') or self.instance.map_display or 'auto'

    def clean(self):
        data = super().clean()
        if self.instance.legacy_zone_id and (data.get('latitude') is not None or data.get('longitude') is not None):
            raise forms.ValidationError('共享的灌溉区域直接使用原区域边界。')
        return data
