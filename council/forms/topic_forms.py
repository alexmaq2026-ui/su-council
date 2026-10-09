"""
Topic Forms
University Council Management System
"""
from django import forms

from council.models import (
    Topic, TopicAttachment, Decision, Vote,
    TopicRecording, TOPIC_CATEGORIES, VOTE_CHOICES,
)


class TopicForm(forms.ModelForm):
    """Form for creating/editing a topic."""

    class Meta:
        model = Topic
        fields = [
            'category', 'order_number', 'title',
            'background', 'priorities', 'mentioned_persons',
        ]
        labels = {
            'category':         'تصنيف الموضوع',
            'order_number':     'رقم الترتيب',
            'title':            'عنوان الموضوع',
            'background':       'الحيثيات والخلفية',
            'priorities':       'الأولويات والمقترحات',
            'mentioned_persons': 'الأشخاص المذكورون',
        }
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-select',
            }),
            'order_number': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'أدخل عنوان الموضوع',
            }),
            'background': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'اكتب الحيثيات والخلفية هنا...',
            }),
            'priorities': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'اكتب الأولويات والمقترحات هنا...',
            }),
            'mentioned_persons': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'أسماء مفصولة بفاصلة',
            }),
        }
        help_texts = {
            'mentioned_persons': 'أدخل الأسماء مفصولة بفاصلة – تُستخدم في البحث',
        }

    def clean_order_number(self):
        n = self.cleaned_data.get('order_number')
        if n is not None and n <= 0:
            raise forms.ValidationError('رقم الترتيب يجب أن يكون عدداً موجباً.')
        return n


class AttachmentForm(forms.ModelForm):
    """Form for uploading a file attachment to a topic."""

    class Meta:
        model = TopicAttachment
        fields = ['file', 'description']
        labels = {
            'file':        'الملف',
            'description': 'وصف الملف',
        }
        widgets = {
            'file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.gif,.zip',
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'وصف مختصر للملف (اختياري)',
            }),
        }


class DecisionForm(forms.ModelForm):
    """Form for creating/editing a decision."""

    class Meta:
        model = Decision
        fields = ['decision_text']
        labels = {
            'decision_text': 'نص القرار',
        }
        widgets = {
            'decision_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'اكتب نص القرار الرسمي هنا...',
                'dir': 'rtl',
            }),
        }

    def clean_decision_text(self):
        text = self.cleaned_data.get('decision_text', '').strip()
        if not text:
            raise forms.ValidationError('نص القرار لا يمكن أن يكون فارغاً.')
        return text


class VoteForm(forms.Form):
    """Form for submitting a vote on a topic."""

    CHOICE_CHOICES = [
        ('approve', 'موافق ✅'),
        ('reject',  'مرفوض ❌'),
        ('reserve', 'متحفظ ⚠️'),
    ]

    choice = forms.ChoiceField(
        label='قرار التصويت',
        choices=CHOICE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )
    notes = forms.CharField(
        label='ملاحظات (اختياري)',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'سبب التحفظ أو الرفض أو أي ملاحظة...',
            'dir': 'rtl',
        }),
    )

    def clean_choice(self):
        choice = self.cleaned_data.get('choice')
        valid = [c[0] for c in self.CHOICE_CHOICES]
        if choice not in valid:
            raise forms.ValidationError('اختيار غير صالح.')
        return choice


class RecordingLabelForm(forms.ModelForm):
    """Form for labeling an audio recording."""

    class Meta:
        model = TopicRecording
        fields = ['label']
        labels = {
            'label': 'تسمية التسجيل',
        }
        widgets = {
            'label': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: النقاش الأول – الجلسة 5',
            }),
        }
