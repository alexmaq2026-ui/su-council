"""
Session Forms
University Council Management System
"""
from django import forms
from django.forms import modelformset_factory

from council.models import CouncilSession, Attendance, ATTENDANCE_STATUS


class SessionForm(forms.ModelForm):
    """Form for creating/editing a council session."""

    class Meta:
        model = CouncilSession
        fields = [
            'session_number', 'title', 'date', 'time',
            'location', 'academic_year', 'status', 'agenda_notes',
        ]
        labels = {
            'session_number': 'رقم الجلسة',
            'title':          'عنوان الجلسة',
            'date':           'تاريخ الجلسة',
            'time':           'وقت الجلسة',
            'location':       'مكان الانعقاد',
            'academic_year':  'السنة الأكاديمية',
            'status':         'الحالة',
            'agenda_notes':   'ملاحظات جدول الأعمال',
        }
        widgets = {
            'session_number': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 5',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'عنوان الجلسة (اختياري)',
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: قاعة مجلس الجامعة',
            }),
            'academic_year': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 2025-2026',
            }),
            'status': forms.Select(attrs={
                'class': 'form-select',
            }),
            'agenda_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'ملاحظات حول جدول الأعمال...',
            }),
        }
        help_texts = {
            'academic_year': 'مثال: 2025-2026',
        }

    def clean_session_number(self):
        number = self.cleaned_data.get('session_number')
        if number is not None and number <= 0:
            raise forms.ValidationError('رقم الجلسة يجب أن يكون عدداً موجباً.')
        return number


class AttendanceForm(forms.ModelForm):
    """Single attendance row for a member."""

    class Meta:
        model = Attendance
        fields = ['member', 'status', 'notes']
        widgets = {
            'member': forms.HiddenInput(),
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'notes':  forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'ملاحظة (اختياري)',
            }),
        }


# FormSet for managing attendance of multiple members at once
AttendanceFormSet = modelformset_factory(
    Attendance,
    form=AttendanceForm,
    fields=['member', 'status', 'notes'],
    extra=0,
    can_delete=False,
)
