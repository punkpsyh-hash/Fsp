"""Ролевые процессы ТЗ: компании, потребности, вакансии, отклики и короткие задачи.
Контакты выдаются через одну разрешённую проекцию; контент компании не считается
верифицированным. Все данные стенда синтетические, внешних ATS-вызовов нет.
"""
from datetime import timedelta
from hashlib import sha256
from fastapi import Depends, HTTPException
from sqlalchemy import select
from . import schemas as S
from .assessment import CATALOG, VERSION
from .skill_evidence import DECLARED_SKILLS
from .work_requirements import catalog as work_catalog, WORK_TASKS_VERSION
from .models import (Application, Attempt, Company, EmployerTask, GradeEvent,
                     HiringNeed, Profile, Search, TaskResponse, User, Vacancy, now)


def attach_product(app, db_session, candidate, employer, actor, public_profile, profile_alias, contact_allowed, audit, aware):
    def company_view(db, uid):
        user=db.get(User,uid)
        company=db.get(Company,uid)
        return {'id':uid,'name':company.name if company else user.label,
                'description':company.description if company else '',
                'industry':company.industry if company else 'Информационные технологии',
                'contact':company.contact if company else user.email,
                'verification':'unverified','demo':True}

    def vacancy_view(db,v):
        return {'id':v.id,'company_id':v.company_id,'company':company_view(db,v.company_id),
                **{name:getattr(v,name) for name in ['title','description','specialization','grade','skills','format','salary_from','salary_to','salary_basis','status','version']},'currency':'RUB','demo':True}

    def own_vacancy(db,user,key,lock=False):
        query=select(Vacancy).where(Vacancy.id==key,Vacancy.company_id==user.id)
        v=db.scalar(query.with_for_update() if lock else query)
        if not v:raise HTTPException(404,'Вакансия не найдена')
        return v

    def application_view(db,a,user):
        result={'id':a.id,'vacancy_id':a.vacancy_id,'candidate_id':a.candidate_id,
                'company_id':a.company_id,'snapshot':a.snapshot,'status':a.status,
                'created_at':a.created_at,'contact_revoked':a.contact_revoked,
                'candidate_alias':profile_alias(db.get(Profile,a.candidate_id))}
        if user.role=='employer' and contact_allowed(db,user.id,a.candidate_id):
            from .models import Contact
            result['contact']=db.get(Contact,a.candidate_id).value
        return result

    def task_view(db,t):
        return {'id':t.id,'company':company_view(db,t.company_id),'title':t.title,
                'description':t.description,'rubric':t.rubric,'specialization':t.specialization,
                'grade':t.grade,'published':t.published,'max_minutes':15,'demo':True}

    def response_view(db,r):
        task=db.get(EmployerTask,r.task_id)
        return {'id':r.id,'task':task_view(db,task),'candidate_alias':profile_alias(db.get(Profile,r.candidate_id)),
                'answer':r.answer,'score':r.score,'feedback':r.feedback,
                'submitted_at':r.submitted_at,'reviewed_at':r.reviewed_at,'demo':True}

    @app.get('/api/v1/catalog',tags=['Справочники'])
    def catalog():
        return {'industry':'it','specializations':CATALOG,'grades':['junior','middle'],
                'assessment_version':VERSION, 'declared_skills':DECLARED_SKILLS,
                'work_tasks':work_catalog(), 'work_tasks_version':WORK_TASKS_VERSION, 'demo':True}

    @app.get('/api/v1/company/profile',tags=['Компания'])
    def company_profile(user=Depends(employer),db=Depends(db_session)):
        return company_view(db,user.id)

    @app.put('/api/v1/company/profile',tags=['Компания'])
    def save_company(body:S.CompanyInput,user=Depends(employer),db=Depends(db_session)):
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        company=db.get(Company,user.id)
        if not company:company=Company(user_id=user.id);db.add(company)
        for key,value in body.model_dump().items():setattr(company,key,value)
        db.get(User,user.id).label=body.name
        audit(db,user,'company.updated',user.id);db.commit()
        return company_view(db,user.id)

    @app.get('/api/v1/company/categories',tags=['Подбор'])
    def categories(user=Depends(employer),db=Depends(db_session)):
        result=[]
        for spec in CATALOG:
            for grade in ('junior','middle'):
                rows=db.scalars(select(Profile).where(Profile.published.is_(True),Profile.specialization==spec,Profile.confirmed_grade==grade)).all()
                result.append({'specialization':spec,'grade':grade,'count':len(rows)})
        return result

    @app.get('/api/v1/company/needs',tags=['Потребности'])
    def needs(user=Depends(employer),db=Depends(db_session)):
        return [{'id':n.id,'title':n.title,'description':n.description,'query':n.query}
                for n in db.scalars(select(HiringNeed).where(HiringNeed.company_id==user.id).order_by(HiringNeed.created_at.desc()))]

    @app.get('/api/v1/company/searches/{search_id}',tags=['Подбор'])
    def restored_search(search_id:str,user=Depends(employer),db=Depends(db_session)):
        saved=db.get(Search,search_id)
        if not saved or saved.company_id!=user.id:raise HTTPException(404,'Подборка не найдена')
        # Сохраняем исторический порядок; текущие права важнее старого snapshot.
        allowed={key for key in saved.candidate_ids if (p:=db.get(Profile,key)) and p.published}
        if saved.explanations is not None:
            rows=[{**row, 'integrity_level': 'review' if row.get('integrity_level')=='flagged' else row.get('integrity_level')}
                  for row in saved.explanations if row['id'] in allowed]
        else:
            # Legacy snapshots не имели компонентов; не придумываем прошлые оценки.
            rows=[public_profile(db.get(Profile,key)) for key in saved.candidate_ids if key in allowed]
        return {'id':saved.id,'query':saved.query,'rows':rows,'created_at':saved.created_at,
                'algorithm_version':saved.algorithm_version,'historical_explanation':saved.explanations is not None,'demo':True}

    @app.post('/api/v1/company/needs',status_code=201,tags=['Потребности'])
    def create_need(body:S.NeedInput,user=Depends(employer),db=Depends(db_session)):
        n=HiringNeed(company_id=user.id,title=body.title,description=body.description,
                     query=body.model_dump(exclude={'title','description'}))
        db.add(n);db.flush();audit(db,user,'need.created',n.id);db.commit()
        return {'id':n.id,'title':n.title,'description':n.description,'query':n.query}

    @app.get('/api/v1/company/vacancies',tags=['Вакансии'])
    def own_vacancies(user=Depends(employer),db=Depends(db_session)):
        return [vacancy_view(db,v) for v in db.scalars(select(Vacancy).where(Vacancy.company_id==user.id).order_by(Vacancy.created_at.desc()))]

    @app.post('/api/v1/company/vacancies',status_code=201,tags=['Вакансии'])
    def create_vacancy(body:S.VacancyInput,user=Depends(employer),db=Depends(db_session)):
        v=Vacancy(company_id=user.id,**body.model_dump(exclude={'expected_version'}))
        db.add(v);db.flush();audit(db,user,'vacancy.created',v.id);db.commit()
        return vacancy_view(db,v)

    @app.put('/api/v1/company/vacancies/{vacancy_id}',tags=['Вакансии'])
    def update_vacancy(vacancy_id:str,body:S.VacancyInput,user=Depends(employer),db=Depends(db_session)):
        v=own_vacancy(db,user,vacancy_id,True)
        if body.expected_version!=v.version:raise HTTPException(409,'Вакансия изменена. Обновите страницу перед сохранением')
        for key,value in body.model_dump(exclude={'expected_version'}).items():setattr(v,key,value)
        v.version+=1;audit(db,user,'vacancy.updated',v.id);db.commit()
        return vacancy_view(db,v)

    @app.get('/api/v1/candidate/vacancies',tags=['Вакансии'])
    def vacancies(user=Depends(candidate),db=Depends(db_session)):
        return [vacancy_view(db,v) for v in db.scalars(select(Vacancy).where(Vacancy.status=='published').order_by(Vacancy.created_at.desc()))]

    @app.post('/api/v1/candidate/vacancies/{vacancy_id}/apply',status_code=201,tags=['Отклики'])
    def apply(vacancy_id:str,user=Depends(candidate),db=Depends(db_session)):
        # Serialize per candidate to make retries and contact grants deterministic.
        p=db.scalar(select(Profile).where(Profile.user_id==user.id).with_for_update())
        previous=db.scalar(select(Application).where(Application.vacancy_id==vacancy_id,Application.candidate_id==user.id))
        if previous:return application_view(db,previous,user)
        if not p.confirmed_grade:raise HTTPException(409,'Пройдите оценку перед откликом')
        v=db.get(Vacancy,vacancy_id)
        if not v or v.status!='published':raise HTTPException(404,'Опубликованная вакансия не найдена')
        a=Application(candidate_id=user.id,company_id=v.company_id,vacancy_id=v.id,snapshot=vacancy_view(db,v))
        db.add(a);db.flush();audit(db,user,'application.sent:contact-consent-v1',a.id);db.commit()
        return application_view(db,a,user)

    @app.get('/api/v1/candidate/applications',tags=['Отклики'])
    def candidate_apps(user=Depends(candidate),db=Depends(db_session)):
        return [application_view(db,a,user) for a in db.scalars(select(Application).where(Application.candidate_id==user.id).order_by(Application.created_at.desc()))]

    @app.get('/api/v1/company/applications',tags=['Отклики'])
    def company_apps(user=Depends(employer),db=Depends(db_session)):
        return [application_view(db,a,user) for a in db.scalars(select(Application).where(Application.company_id==user.id).order_by(Application.created_at.desc()))]

    @app.post('/api/v1/company/applications/{application_id}/decision',tags=['Отклики'])
    def app_decision(application_id:str,body:S.ApplicationDecision,user=Depends(employer),db=Depends(db_session)):
        a=db.scalar(select(Application).where(Application.id==application_id,Application.company_id==user.id).with_for_update())
        if not a:raise HTTPException(404,'Отклик не найден')
        if a.status==body.status:return application_view(db,a,user)
        if a.status not in {'sent','viewed'}:raise HTTPException(409,'Отклик завершён')
        a.status=body.status
        if a.status=='declined':a.contact_revoked=True
        audit(db,user,'application.'+a.status,a.id);db.commit()
        return application_view(db,a,user)

    @app.post('/api/v1/candidate/applications/{application_id}/withdraw',tags=['Отклики'])
    def withdraw_app(application_id:str,user=Depends(candidate),db=Depends(db_session)):
        a=db.scalar(select(Application).where(Application.id==application_id,Application.candidate_id==user.id).with_for_update())
        if not a:raise HTTPException(404,'Отклик не найден')
        if a.status!='withdrawn':
            a.status='withdrawn';a.contact_revoked=True;audit(db,user,'application.withdrawn',a.id);db.commit()
        return application_view(db,a,user)

    @app.get('/api/v1/candidate/assessment-history',tags=['Оценка'])
    def history(user=Depends(candidate),db=Depends(db_session)):
        attempts=db.scalars(select(Attempt).where(Attempt.candidate_id==user.id).order_by(Attempt.created_at.desc())).all()
        events=db.scalars(select(GradeEvent).where(GradeEvent.candidate_id==user.id).order_by(GradeEvent.created_at.desc())).all()
        return {'attempts':[{'id':a.id,'grade':a.grade,'specialization':a.specialization,'version':a.blueprint_version,
                             'context':a.context,'created_at':a.created_at,'submitted_at':a.submitted_at,'result':a.result} for a in attempts],
                'events':[{'specialization':g.specialization,'from':g.previous_grade,'to':g.grade,'passed':g.passed,'at':g.created_at} for g in events]}

    @app.get('/api/v1/company/tasks',tags=['Короткие задания'])
    def own_tasks(user=Depends(employer),db=Depends(db_session)):
        return [task_view(db,t) for t in db.scalars(select(EmployerTask).where(EmployerTask.company_id==user.id))]

    @app.post('/api/v1/company/tasks',status_code=201,tags=['Короткие задания'])
    def create_task(body:S.TaskInput,user=Depends(employer),db=Depends(db_session)):
        t=EmployerTask(company_id=user.id,**body.model_dump());db.add(t);db.flush()
        audit(db,user,'task.created',t.id);db.commit();return task_view(db,t)

    @app.get('/api/v1/candidate/tasks',tags=['Короткие задания'])
    def suggested_tasks(user=Depends(candidate),db=Depends(db_session)):
        p=db.get(Profile,user.id)
        moment=now()
        history=db.scalars(select(TaskResponse).where(TaskResponse.candidate_id==user.id).order_by(TaskResponse.submitted_at.desc())).all()
        due=aware(history[0].submitted_at)+timedelta(days=7) if history else moment
        answered={r.task_id for r in history}
        available=db.scalars(select(EmployerTask).where(EmployerTask.published.is_(True),EmployerTask.specialization==p.specialization,EmployerTask.grade==p.confirmed_grade).order_by(EmployerTask.id)).all()
        eligible=[t for t in available if t.id not in answered] if due<=moment else []
        recommendation=None
        if eligible:
            # Одно адресное предложение на календарную неделю UTC; GET не пишет БД.
            period=moment.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=moment.weekday())
            key=f'weekly-task-v1:{user.id}:{p.specialization}:{p.confirmed_grade}:{period.isoformat()}'
            # Ранг каждого задания не зависит от длины списка: снятие другого
            # задания не меняет выбор. Изменение подходящего пула может обновить
            # предложение; это рекомендация, а не закреплённое назначение.
            selected=min(eligible,key=lambda t:sha256((key+':'+t.id).encode()).hexdigest())
            recommendation={'id':sha256((key+':'+selected.id).encode()).hexdigest()[:24],
                            'task':task_view(db,selected),'period_starts_at':period,
                            'next_period_at':period+timedelta(days=7)}
        state='offered' if recommendation else ('no-grade' if not p.confirmed_grade else 'cooldown' if due>moment else 'no-tasks')
        return {'available':[task_view(db,t) for t in eligible],
                'next_at':due,'responses':[response_view(db,r) for r in history],
                'recommendation':recommendation,'recommendation_state':state}

    @app.post('/api/v1/candidate/tasks/{task_id}/submit',status_code=201,tags=['Короткие задания'])
    def submit_task(task_id:str,body:S.TaskAnswer,user=Depends(candidate),db=Depends(db_session)):
        p=db.scalar(select(Profile).where(Profile.user_id==user.id).with_for_update())
        existing=db.scalar(select(TaskResponse).where(TaskResponse.task_id==task_id,TaskResponse.candidate_id==user.id))
        if existing:
            if existing.answer!=body.answer:raise HTTPException(409,'Ответ уже отправлен')
            return response_view(db,existing)
        t=db.get(EmployerTask,task_id)
        if not t or not t.published or t.specialization!=p.specialization or t.grade!=p.confirmed_grade:raise HTTPException(404,'Задание не найдено')
        last=db.scalar(select(TaskResponse).where(TaskResponse.candidate_id==user.id).order_by(TaskResponse.submitted_at.desc()))
        if last and aware(last.submitted_at)+timedelta(days=7)>now():raise HTTPException(409,'Короткое задание доступно раз в семь суток')
        r=TaskResponse(task_id=t.id,candidate_id=user.id,answer=body.answer);db.add(r);db.flush()
        audit(db,user,'task.submitted',r.id);db.commit();return response_view(db,r)

    @app.get('/api/v1/company/task-responses',tags=['Короткие задания'])
    def task_responses(user=Depends(employer),db=Depends(db_session)):
        rows=db.scalars(select(TaskResponse).join(EmployerTask).where(EmployerTask.company_id==user.id)).all()
        return [response_view(db,r) for r in rows]

    @app.post('/api/v1/company/task-responses/{response_id}/review',tags=['Короткие задания'])
    def review(response_id:str,body:S.TaskReview,user=Depends(employer),db=Depends(db_session)):
        r=db.scalar(select(TaskResponse).join(EmployerTask).where(TaskResponse.id==response_id,EmployerTask.company_id==user.id).with_for_update(of=TaskResponse))
        if not r:raise HTTPException(404,'Ответ не найден')
        if r.reviewed_at:
            if r.score!=body.score or r.feedback!=body.feedback:raise HTTPException(409,'Ответ уже оценён')
            return response_view(db,r)
        r.score,r.feedback,r.reviewed_at=body.score,body.feedback,now()
        p=db.scalar(select(Profile).where(Profile.user_id==r.candidate_id).with_for_update())
        if body.score>=70:p.activity_at=r.reviewed_at
        audit(db,user,'task.reviewed',r.id);db.commit();return response_view(db,r)
