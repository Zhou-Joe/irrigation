from django import forms
from .models import Location
from .work_parameters import definitions


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'code', 'kind', 'map_display', 'parent', 'description', 'latitude', 'longitude', 'parameters']
        labels = {'name': '地点名称', 'code': '地点编号（选填）', 'kind': '地点类型', 'parent': '上级地点（选填）',
                  'map_display': '地图显示方式', 'description': '位置说明',
                  'latitude': '纬度（选填）', 'longitude': '经度（选填）', 'parameters': '地点填报参数（JSON 配置）'}
        help_texts = {'kind': '图钉的图标和颜色按地点类型区分。',
                      'map_display': '建筑等地点可在下方地图点选；诱捕笼和蜂箱使用专用图钉。未定位的地点仍可用于工单。'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3}), 'parameters': forms.Textarea(attrs={'rows': 5, 'spellcheck':'false'})}

    def __init__(self, *args, parents, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['map_display'].required = False
        self.fields['parent'].queryset = parents
        self.fields['parent'].label_from_instance = lambda obj: obj.name
        if self.instance.legacy_zone_id:
            self.fields['latitude'].disabled = True
            self.fields['longitude'].disabled = True

    def clean_map_display(self):
        if self.cleaned_data.get('kind') in Location.POINT_KINDS:
            return 'pin'
        return self.cleaned_data.get('map_display') or self.instance.map_display or 'auto'

    def clean_parameters(self):
        # Map creation and older clients may omit this administrative field.
        if self.is_bound and 'parameters' not in self.data:
            return self.instance.parameters
        try:
            return definitions(self.cleaned_data.get('parameters'), allow_location=False)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean(self):
        data = super().clean()
        if self.instance.legacy_zone_id and (data.get('latitude') is not None or data.get('longitude') is not None):
            raise forms.ValidationError('共享的灌溉区域直接使用原区域边界。')
        return data
