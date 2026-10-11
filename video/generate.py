"""Сборка редактируемого JSX и внешних субтитров из проверенного storyboard.

Использует только стандартную библиотеку; запуск — в Docker Python.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
spec = json.loads((root / 'storyboard.json').read_text(encoding='utf-8'))
fps = spec['fps']
assert fps == 25, 'Частота должна совпадать с исходной записью 25 fps'
q = lambda value: json.dumps(value, ensure_ascii=False)
frame = lambda seconds: round(seconds * fps)
cursor = frame(spec['introSeconds'])
subtitles = []
chapters = []
nodes = [f'<Series.Sequence name="Вступление" durationInFrames={{{cursor}}} premountFor={{fps}}><Intro /></Series.Sequence>']

for chapter in spec['chapters']:
    chapters.append({'number': chapter['number'], 'title': chapter['title'], 'startSeconds': cursor / fps})
    duration = frame(spec['chapterSeconds'])
    nodes.append(f'<Series.Sequence name={{{q(chapter["title"])}}} durationInFrames={{{duration}}} premountFor={{fps}}><Chapter number={{{q(chapter["number"])}}} title={{{q(chapter["title"])}}} subtitle={{{q(chapter["subtitle"])}}} /></Series.Sequence>')
    subtitles.append({'text': chapter['title'] + '. ' + chapter['subtitle'], 'startMs': round(cursor / fps * 1000), 'endMs': round((cursor+duration)/fps*1000), 'timestampMs': None, 'confidence': None})
    cursor += duration
    for clip_index, (start, end) in enumerate(chapter['clips']):
        duration = frame(end)-frame(start)
        captions = []
        for a,b,text in chapter['captions']:
            a,b = max(a,start), min(b,end)
            if b > a:
                captions.append({'text':text,'startMs':round(a*1000),'endMs':round(b*1000),'timestampMs':None,'confidence':None,'pageBreakAfter':True})
                # Внешние подписи используют фактические целые кадры trim.
                # Это исключает перекрытие на 20 мс у границ .3/.5 секунды.
                caption_start = cursor + max(0, frame(a)-frame(start))
                caption_end = cursor + min(duration, frame(b)-frame(start))
                subtitles.append({'text':text,'startMs':round(caption_start/fps*1000),'endMs':round(caption_end/fps*1000),'timestampMs':None,'confidence':None})
        nodes.append(f'''<Series.Sequence name={{{q(chapter['title']+' · '+str(clip_index+1))}}} trimBefore={{{frame(start)}}} durationInFrames={{{duration}}} premountFor={{fps}}>
          <Screen number={{{q(chapter['number'])}}} title={{{q(chapter['title'])}}} meaning={{{q(chapter['meaning'])}}} caution={{{q(chapter.get('caution',''))}}}>
            <FrameVideo style={{{{position:'absolute',left:64,top:110,width:1328,height:830}}}} />
            <BasicCaptions name="Пояснение действия" width={{3318}} combineTokensWithinMilliseconds={{0}} style={{{{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}}}} captions={{{q(captions)}}} />
          </Screen>
        </Series.Sequence>''')
        cursor += duration

chapters.append({'number':'09','title':'Защита попытки и генератор: схемы правил','startSeconds':cursor/fps})
rules_start=cursor
nodes.append(f'<Series.Sequence name="Защита и генератор: схемы" durationInFrames={{{frame(spec["rulesSeconds"])}}} premountFor={{fps}}><Rules /></Series.Sequence>')
cursor+=frame(spec['rulesSeconds'])
for a,b,text in [(0,10,'Защита: версии форм, параметры задач и контроль целостности попытки. Разбор доступен после завершения.'),(10,20,'Генератор Qwen предлагает черновик. Сервер проверяет структуру, автор решает вопрос публикации. Показана схема, не вызов модели.')]:
    subtitles.append({'text':text,'startMs':round((rules_start/fps+a)*1000),'endMs':round((rules_start/fps+b)*1000),'timestampMs':None,'confidence':None})
chapters.append({'number':'10','title':'Итог и доступ жюри','startSeconds':cursor/fps})
outro_start=cursor
nodes.append(f'<Series.Sequence name="Итог и доступ жюри" durationInFrames={{{frame(spec["outroSeconds"])}}} premountFor={{fps}}><Outro /></Series.Sequence>')
cursor+=frame(spec['outroSeconds'])
for a,b,text in [(0,8,'Профиль → Оценка → Категория → Подбор → Согласие → Контакт.'),(8,22,'GitHub: публичный github.com/punkpsyh-hash/Fsp, ветка main. Скачать ZIP или выполнить git clone; приглашение не требуется.'),(22,36,'Стенд: fsptest.kolesnikovny.ru. Отдельный пароль от владельца. Полный запуск — Docker и README.')]:
    subtitles.append({'text':text,'startMs':round((outro_start/fps+a)*1000),'endMs':round((outro_start/fps+b)*1000),'timestampMs':None,'confidence':None})
(root/'src/Root.tsx').write_text('''// Создано generate.py из storyboard.json. Клипы и подписи представлены отдельными JSX-узлами.
import React from 'react';
import {AbsoluteFill, Composition, Series, useVideoConfig} from 'remotion';
import {FrameVideo} from './FrameVideo';
import {BasicCaptions} from './basic-captions';
import {Intro, Chapter, Screen, Rules, Outro, Progress} from './Graphics';
const Demo: React.FC = () => {
  const {fps}=useVideoConfig();
  return <AbsoluteFill><Series>\n'''+ '\n'.join(nodes)+f'''\n</Series><Progress /></AbsoluteFill>;
}};
export const Root: React.FC = () => <Composition id="FspDemo" component={{Demo}} durationInFrames={{{cursor}}} fps={{25}} width={{1920}} height={{1080}} />;
''',encoding='utf-8')
out=root.parent/'docs/delivery'
def stamp(ms,separator):
    sec,milli=divmod(ms,1000); minute,sec=divmod(sec,60); hour,minute=divmod(minute,60)
    return f'{hour:02}:{minute:02}:{sec:02}{separator}{milli:03}'
subtitles.insert(0,{'text':'ФСП · Карьерный профиль. Студия 37. Реальная запись на синтетических данных.','startMs':0,'endMs':6000,'timestampMs':None,'confidence':None})
for extension,separator in [('srt',','),('vtt','.')]:
    blocks=[]
    for i,c in enumerate(subtitles,1):
        blocks.append(f'{i}\n{stamp(c["startMs"],separator)} --> {stamp(c["endMs"],separator)}\n{c["text"]}\n')
    (out/f'demo-explained.{extension}').write_text(('WEBVTT\n\n' if extension=='vtt' else '')+'\n'.join(blocks),encoding='utf-8')
(out/'demo-explained-captions.json').write_text(json.dumps(subtitles,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(out/'demo-explained-chapters.json').write_text(json.dumps({'fps':fps,'durationFrames':cursor,'durationSeconds':cursor/fps,'chapters':chapters},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'frames':cursor,'seconds':cursor/fps,'captions':len(subtitles),'chapters':len(chapters)}))
