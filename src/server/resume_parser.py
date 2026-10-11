"""Отдельный ограниченный процесс разбора текстового PDF. Не OCR и не исполнение PDF."""
import json
import logging
import re
import sys
from io import BytesIO


def parse(data):
    if not data.startswith(b'%PDF-') or len(data)>2*1024*1024:
        raise ValueError('Нужен PDF размером до 2 МБ')
    from pypdf import PdfReader
    logging.getLogger('pypdf').setLevel(logging.CRITICAL)
    reader=PdfReader(BytesIO(data),strict=True)
    if reader.is_encrypted or len(reader.pages)>10:
        raise ValueError('Допустим незашифрованный PDF до 10 страниц')
    text='\n'.join((p.extract_text() or '')[:10000] for p in reader.pages)[:30000]
    if not text.strip():raise ValueError('Текст не распознан. Для сканов используйте ручную форму')
    # Собираем только предлагаемые поля. Сырой текст не сохраняется и не публикуется.
    name=re.search(r'(?:ФИО|Имя|Full name)\s*[:：]\s*([^\n]{2,120})',text,re.I)
    experience=re.search(r'(?:Стаж|Опыт)\s*[:：]?\s*(\d{1,2})\s*(?:лет|год)',text,re.I)
    contact=re.search(r'[A-Za-z0-9._+-]+@example\.invalid',text,re.I)
    lower=text.lower()
    skills=[skill for skill in ('python','sql','javascript','html','http','testing') if skill in lower]
    design_terms=('дизайнер','ui/ux','ux/ui','figma','фигма','designer','wireframe','прототип')
    specialization='design' if any(k in lower for k in design_terms) else 'frontend' if any(k in lower for k in ('frontend','фронтенд','javascript')) else 'qa' if any(k in lower for k in ('тестировщик','qa','тестирование')) else 'backend'
    grade='middle' if 'middle' in lower else 'junior'
    role_terms={'developer':('разработчик','developer','программист'),
                'tester':('тестировщик','tester','qa engineer'),
                'team-lead':('тимлид','team lead','team-lead','руководитель команды'),
                'analyst':('аналитик','analyst'),
                'designer':('дизайнер','designer','ui/ux','ux/ui')}
    soft_terms={'communication':('коммуникац','communication','общение'),
                'teamwork':('командная работа','работа в команде','teamwork'),
                'planning':('планирован','planning'),
                'mentoring':('наставнич','ментор','mentoring')}
    def section(labels,limit):
        match=re.search(r'(?:'+labels+r')\s*[:：]\s*([^\n]+)',text,re.I)
        return match.group(1).strip()[:limit] if match else ''
    resume={'full_name':name.group(1).strip() if name else 'Синтетический кандидат',
            'years_experience':min(60,int(experience.group(1))) if experience else 0,
            'roles':[role for role,terms in role_terms.items() if any(term in lower for term in terms)],
            'soft_skills':[skill for skill,terms in soft_terms.items() if any(term in lower for term in terms)],
            'education':section('Образование|Education',1000),
            'about':section('О себе|About|Summary',2000)}
    return {'resume':resume,'contact':contact.group(0).lower() if contact else None,
            'specialization':specialization,'claimed_grade':grade,'claimed_skills':skills,
            'warnings':['Эвристический разбор: подтвердите имя, контакт, роли, стаж и софт-навыки перед сохранением. Навыки и грейд не подтверждаются импортом.',
                        'Контакты стенда ограничены example.invalid; реальный адрес не переносится.',
                        'OCR, встраиваемые скрипты и внешние ссылки не выполняются.'],'demo':True}


if __name__=='__main__':
    try:
        if sys.platform!='win32':
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(4,4))
            resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
        print(json.dumps(parse(sys.stdin.buffer.read(2*1024*1024+1)),ensure_ascii=False))
    except Exception:
        print(json.dumps({'error':'PDF не удалось безопасно разобрать. Используйте ручную форму'},ensure_ascii=False))
        sys.exit(1)
