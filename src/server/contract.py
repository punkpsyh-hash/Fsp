"""Точные выходные проекции локального API, дополнение схем входа FastAPI.
Схемы сверяются с ответами тестового стенда; это не контракт внешнего реестра ФСП.
"""
def enrich(schema):
    models=schema['components'].setdefault('schemas',{})
    def ref(name):return {'$ref':'#/components/schemas/'+name}
    def array(items):return {'type':'array','items':items}
    string={'type':'string'};boolean={'type':'boolean'};integer={'type':'integer'};number={'type':'number'}
    nullable=lambda kind:{'anyOf':[kind,{'type':'null'}]}
    stamp={'type':'string','format':'date-time'};blob={'type':'object','additionalProperties':True}
    def model(name,props,required=None):
        models[name]={'type':'object','properties':props,'required':list(props) if required is None else required}
        return ref(name)
    demo={'demo':{'type':'boolean','const':True}}
    account=model('AccountView',{'id':string,'role':{'enum':['candidate','employer']},'label':string})
    session=model('SessionView',{'id':string,'role':{'enum':['candidate','employer']},'label':string,'csrf':string,'email':string,**demo},['id','role','label','csrf','demo'])
    evidence=model('FspEvidenceView',{'event':string,'discipline':string,'role':string,'place':integer,'date':string,'source':{'const':'local-mock'},**demo})
    experience=model('ExperienceView',{'years_experience':integer,'roles':array(string),'soft_skills':array(string)})
    assessment_evidence=model('AssessmentSkillEvidenceView',{'skill':string,'score':nullable(number),'correct':nullable(integer),'total':nullable(integer),'version':nullable(string),'assessed_at':nullable(stamp),'source':{'enum':['assessment','legacy-assessment']}})
    practice_evidence=model('PracticeSkillEvidenceView',{'skill':string,'score':number,'tasks':integer,'total_tasks':integer,'completed_at':nullable(stamp),'source':{'enum':['platform-practice','employer-practice']}})
    skills_evidence=model('SkillEvidenceView',{'declared':array(string),'assessment':array(assessment_evidence),'practice':array(practice_evidence),'limitations':array(string)})
    props={'id':string,'alias':string,'specialization':{'enum':['backend','frontend','qa','design']},'confirmed_grade':nullable({'enum':['junior','middle']}),'skills':array(string),'formats':array(string),'salary_min':integer,'test_score':number,'assessed_at':nullable(stamp),'fsp_state':string,'fsp_evidence':array(evidence),'activity_at':nullable(stamp),'experience':experience,'integrity_level':nullable({'enum':['clean','review']}),**demo}
    props['skill_evidence']=skills_evidence
    required_profile=[key for key in props if key not in ('skill_evidence','integrity_level')]
    public=model('CandidateView',props,required_profile)
    company_candidate=model('CompanyCandidateView',{**props,'contact':string},list(props))
    grant=model('GrantView',{'id':string,'label':string})
    own=model('CandidateSelfView',{**props,'claimed_grade':string,'published':boolean,'industry':string,'resume':ref('ResumeInput'),'fsp_member_id':nullable(string),'contact':string,'grade_changed_at':nullable(stamp),'contact_grants':array(grant)})
    components=model('RankingComponentsView',{'assessment':number,'skills':number,'fsp':number,'freshness':number})
    work_match=model('WorkTaskMatchView',{'id':string,'label':string,'required_skills':array(string),'matched_skills':array(string),'missing_skills':array(string),'status':{'enum':['covered','partial','gap']}})
    row=model('RankedCandidateView',{**props,'score':number,'matched':array(string),'missing':array(string),'fsp_bonus':number,'components':components,'work_matches':array(work_match)},required_profile+['score','matched','missing','fsp_bonus','components'])
    query=ref('SearchInput')
    result=model('SearchResultView',{'id':string,'candidate_ids':array(string),'rows':array(row),'created_at':stamp,'algorithm_version':string,**demo})
    snapshot=model('SearchSnapshotView',{'id':string,'query':query,'created_at':stamp})
    search_page=model('SearchHistoryPage',{'items':array(snapshot),'total':integer,'offset':integer,'limit':integer})
    restored=model('RestoredSearchView',{'id':string,'query':query,'rows':array({'anyOf':[row,public]}),'created_at':stamp,'algorithm_version':string,'historical_explanation':boolean,**demo})
    breakdown=model('SkillScoreView',{'skill':string,'correct':integer,'total':integer,'score':number})
    integrity_signal=model('IntegritySignalView',{'code':string,'level':{'enum':['review','flagged']},'value':number,'message':string})
    integrity_result=model('IntegrityResultView',{'level':{'enum':['clean','review','flagged']},'signals':array(integrity_signal),'hold':boolean,'enforced':boolean})
    score=model('AssessmentResultView',{'score':number,'skills':array(string),'passed':boolean,'confirmed':boolean,'borderline':boolean,'needs_confirmation':boolean,'stage':integer,'stage_scores':array(number),'cooldown':boolean,'integrity':integrity_result,'breakdown':array(breakdown),'version':string,'limitation':string,**demo},['score','skills','passed','version','limitation','demo'])
    question=model('QuestionView',{'id':string,'skill':string,'title':string,'options':array(string)},['id','skill','title','options'])
    feedback_skill=model('FeedbackSkillView',{'skill':string,'correct':integer,'total':integer,'score':number,'status':{'enum':['strong','review']},'topics':array(string),'recommendation':string})
    feedback_question=model('FeedbackQuestionView',{'id':string,'skill':string,'status':{'enum':['correct','incorrect','unanswered']},'selected_answer':nullable(string),'correct_answer':string,'explanation':string})
    feedback=model('AssessmentFeedbackView',{'threshold':integer,'correct':integer,'total':integer,'needed_correct':integer,'skills':array(feedback_skill),'questions':array(feedback_question)})
    attempt=model('AttemptView',{'id':string,'questions':array(question),'grade':string,'specialization':{'enum':['backend','frontend','qa','design']},'context':blob,'version':string,'result':nullable(score),'feedback':nullable(feedback),'answers':{'type':'object','additionalProperties':string},'revision':integer,'expires_at':stamp,**demo},['id','questions','grade','context','answers','revision','expires_at','demo'])
    offer_props={'id':string,'company_id':string,'company_name':string,'company_contact':string,'candidate_id':string,'candidate_alias':string,'description':string,'salary_from':integer,'salary_to':integer,'salary_basis':{'enum':['gross','net']},'currency':{'const':'RUB'},'vacancy_id':nullable(string),'status':{'enum':['sent','viewed','accepted','declined','withdrawn','expired']},'expires_at':stamp,'contact_revoked':boolean,**demo}
    offer=model('InvitationView',{**offer_props,'contact':string},list(offer_props))
    company=model('CompanyView',{'id':string,'name':string,'description':string,'industry':string,'contact':string,'verification':{'const':'unverified'},**demo})
    need=model('NeedView',{'id':string,'title':string,'description':string,'query':query})
    vacancy=model('VacancyView',{'id':string,'company_id':string,'company':company,'title':string,'description':string,'specialization':string,'grade':string,'skills':array(string),'format':string,'salary_from':integer,'salary_to':integer,'salary_basis':string,'status':string,'version':integer,'currency':{'const':'RUB'},**demo})
    app_props={'id':string,'vacancy_id':string,'candidate_id':string,'company_id':string,'snapshot':vacancy,'status':{'enum':['sent','viewed','accepted','declined','withdrawn']},'created_at':stamp,'contact_revoked':boolean,'candidate_alias':string}
    application=model('ApplicationView',{**app_props,'contact':string},list(app_props))
    task=model('EmployerTaskView',{'id':string,'company':company,'title':string,'description':string,'rubric':string,'specialization':string,'grade':string,'published':boolean,'max_minutes':{'const':15},**demo})
    task_response=model('TaskResponseView',{'id':string,'task':task,'candidate_alias':string,'answer':string,'score':nullable(integer),'feedback':nullable(string),'submitted_at':stamp,'reviewed_at':nullable(stamp),**demo})
    weekly_task=model('WeeklyTaskView',{'id':string,'task':task,'period_starts_at':stamp,'next_period_at':stamp})
    task_list=model('SuggestedTasksView',{'available':array(task),'next_at':stamp,'responses':array(task_response),
                                       'recommendation':nullable(weekly_task),'recommendation_state':{'enum':['offered','no-grade','cooldown','no-tasks']}})
    history_attempt=model('HistoricalAttemptView',{'id':string,'grade':string,'specialization':string,'version':string,'context':blob,'created_at':stamp,'submitted_at':nullable(stamp),'result':nullable(score)})
    event=model('GradeEventView',{'specialization':string,'from':nullable(string),'to':nullable(string),'passed':boolean,'at':stamp})
    history=model('AssessmentHistoryView',{'attempts':array(history_attempt),'events':array(event)})
    preview=model('ResumePreviewView',{'resume':ref('ResumeInput'),'contact':nullable(string),'specialization':string,'claimed_grade':string,'claimed_skills':array(string),'warnings':array(string),**demo})
    category=model('CategoryView',{'specialization':string,'grade':string,'count':integer})
    declared_skill=model('DeclaredSkillCatalogView',{'id':string,'label':string,'specializations':array(string)})
    work_task=model('WorkTaskCatalogView',{'id':string,'label':string,'description':string,'skills':array(string),'specialization':string})
    catalogue=model('CatalogView',{'industry':{'const':'it'},'specializations':{'type':'object','additionalProperties':{'type':'object','properties':{'label':string,'skills':array(string)},'required':['label','skills']}},'grades':array(string),'assessment_version':string,'declared_skills':array(declared_skill),'work_tasks':array(work_task),'work_tasks_version':string,**demo})
    mail=model('MailView',{'id':string,'email':string,'token':string,'expires_at':stamp,**demo})
    message=model('MessageView',{'message':string,**demo})
    delivery=model('DeliveryView',{'message':string,'transport':{'enum':['local-mailbox','smtp']},'delivery':{'enum':['ready','failed']},**demo})
    fsp=model('FspLinkView',{'state':string,'previous_state':string,'signal':number,**demo})
    healthy=model('HealthView',{'status':{'const':'ok'},'mode':{'const':'local-demo'},'version':string})
    saved=model('SavedView',{'saved':{'const':True}})
    publication=model('PublicationView',{'published':boolean})
    error=model('ErrorView',{'code':string,'message':string,'request_id':string,'details':array({'type':'object','properties':{'field':string,'message':string},'required':['field','message']})},['code','message','request_id'])
    outputs={'health':healthy,'accounts':array(account),'demo_login':session,'password_login':session,'verify':session,'me':session,'register':delivery,'request_login':message,'mail_sink':array(mail),'get_profile':own,'update_profile':saved,'consent':publication,'start_attempt':attempt,'get_attempt':attempt,'submit':score,'fsp':fsp,'search':result,'searches':array(snapshot),'candidate_detail':company_candidate,'get_shortlist':array(public),'invite':offer,'company_offers':array(offer),'candidate_offers':array(offer),'view_offer':offer,'decide':offer,'withdraw':offer,'resume_preview':preview,
             'catalog':catalogue,'company_profile':company,'save_company':company,'categories':array(category),'needs':array(need),'create_need':need,'restored_search':restored,'own_vacancies':array(vacancy),'create_vacancy':vacancy,'update_vacancy':vacancy,'vacancies':array(vacancy),'apply':application,'candidate_apps':array(application),'company_apps':array(application),'app_decision':application,'withdraw_app':application,'history':history,'own_tasks':array(task),'create_task':task,'suggested_tasks':task_list,'submit_task':task_response,'task_responses':array(task_response),'review':task_response}
    outputs.update({'active_assessment':nullable(attempt),'save_attempt_draft':attempt,'searches_page':search_page})
    for path,methods in schema['paths'].items():
        for method,spec in methods.items():
            name=spec['operationId'].split('_api_',1)[0]
            for code,details in spec['responses'].items():
                if code=='204':continue
                if name in {'self_pdf','company_pdf'} and code=='200':
                    details['content']={'application/pdf':{'schema':{'type':'string','format':'binary'}}}
                elif code.startswith('2'):
                    if name in outputs:
                        details['content']={'application/json':{'schema':outputs[name]}}
                    else:
                        # Новые модули определяют точные response_model самостоятельно.
                        described=details.get('content',{})
                        if not described or any(not media.get('schema') for media in described.values()):
                            raise ValueError('Undocumented API response: '+name)
            for code,description in [('401','Нет действующей сессии'),('403','Роль, источник или CSRF не разрешены'),('404','Запись отсутствует или не принадлежит пользователю'),('409','Конфликт состояния, версии или срока'),('422','Некорректные поля'),('429','Лимит запросов'),('503','Компонент недоступен')]:
                spec['responses'][code]={'description':description,'content':{'application/json':{'schema':error}}}
            if name=='bank_suggest_task':
                spec['responses']['502']={'description':'Ответ модели не прошёл проверку задания','content':{'application/json':{'schema':error}}}
            if name=='fsp_token':
                spec['responses']['400']={'description':'invalid_grant: код недействителен, использован или не совпал PKCE','content':{'application/json':{'schema':error}}}
            if name in {'fsp_authorize_form','fsp_authorize_submit'}:
                spec['responses']['400']={'description':'Форма входа с сообщением об ошибке','content':{'text/html':{'schema':string}}}
            if name=='resume_preview':
                spec['requestBody']={'required':True,'content':{'application/pdf':{'schema':{'type':'string','format':'binary','maxLength':2097152}}}}
                for code,description in [('413','PDF больше 2 МБ'),('415','Неверный тип файла')]:spec['responses'][code]={'description':description,'content':{'application/json':{'schema':error}}}
            if name=='bank_import_preview':
                spec['requestBody']={'required':True,'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary','maxLength':2097152}}}}
                for code,description in [('413','Материал больше 2 МБ')]:
                    spec['responses'][code]={'description':description,'content':{'application/json':{'schema':error}}}
    return schema
