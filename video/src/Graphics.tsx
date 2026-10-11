import React from 'react';
import {AbsoluteFill, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

export const colors = {bg: '#17141e', paper: '#faf9fc', ink: '#17141e', muted: '#aaa3b5', line: '#45404e', accent: '#ff0053', purple: '#520978'};
export const Font: React.FC = () => <style>{`@font-face {font-family:FspVideo;src:url('${staticFile('DejaVuSans.ttf')}')} * {box-sizing:border-box}`}</style>;
const enter = (frame: number, fps: number, delay = 0) => spring({frame: frame-delay, fps, config: {damping: 200}});

export const Intro: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const s = enter(frame, fps, 3);
  return <AbsoluteFill style={{background: colors.bg, color: 'white', fontFamily: 'FspVideo', padding: '100px 110px'}}>
    <Font />
    <div style={{fontSize: 29, color: colors.muted, letterSpacing: 3}}>СТУДИЯ 37 · ЛЦТ 2026 · СПЕЦИАЛЬНЫЙ ТРЕК ФСП</div>
    <div style={{height: 6, width: 1700*s, background: colors.accent, marginTop: 52}} />
    <div style={{opacity: s, transform: `translateY(${35*(1-s)}px)`, marginTop: 64, fontSize: 108, lineHeight: 1.08, fontWeight: 700}}>ФСП<br/>Карьерный профиль</div>
    <div style={{fontSize: 39, marginTop: 55, maxWidth: 1580}}>От подтверждения навыков — к предложению работы<br/>и управляемому доступу к контакту.</div>
    <div style={{position: 'absolute', bottom: 100, fontSize: 27, color: colors.muted}}>Реальная запись интерфейса · синтетические данные · пояснения без звука</div>
  </AbsoluteFill>;
};

export const Chapter: React.FC<{number: string; title: string; subtitle: string}> = ({number, title, subtitle}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const s = enter(frame, fps);
  return <AbsoluteFill style={{background: colors.bg, color: 'white', fontFamily: 'FspVideo', padding: '120px 110px'}}>
    <Font />
    <div style={{fontSize: 28, color: colors.muted}}>ФСП · КАРЬЕРНЫЙ ПРОФИЛЬ</div>
    <div style={{fontSize: 180, color: colors.accent, marginTop: 72, opacity: s, transform: `translateX(${-60*(1-s)}px)`}}>{number}</div>
    <div style={{height: 3, width: 1700*s, background: colors.line, marginTop: 24}} />
    <div style={{fontSize: 78, fontWeight: 700, marginTop: 40, opacity: s}}>{title}</div>
    <div style={{fontSize: 35, color: '#d8d2e2', marginTop: 28}}>{subtitle}</div>
  </AbsoluteFill>;
};

export const Screen: React.FC<{number: string; title: string; meaning: string; caution?: string; children: React.ReactNode}> = ({number,title,meaning,caution,children}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const s=enter(frame,fps);
  return <AbsoluteFill style={{background: colors.bg, color: 'white', fontFamily: 'FspVideo'}}>
    <Font />
    <div style={{position:'absolute', left:64, top:30, fontSize:27}}>ФСП · Карьерный профиль</div>
    <div style={{position:'absolute', right:64, top:34, fontSize:22, color:'#c9c3d4'}}>Полный локальный контур · Синтетические данные</div>
    <div style={{position:'absolute', left:64, top:82, height:3, width:1792, background:colors.line}} />
    {children}
    <div style={{position:'absolute', left:1440, top:140, width:405, opacity:s}}>
      <div style={{fontSize:72,color:colors.accent}}>{number}<span style={{fontSize:24,color:colors.muted}}> / 08</span></div>
      <div style={{fontSize:42, fontWeight:700, lineHeight:1.16, marginTop:32}}>{title}</div>
      <div style={{height:3,background:colors.accent,width:72,marginTop:35}} />
      <div style={{fontSize:29,lineHeight:1.45,marginTop:30,color:'#e2dcea'}}>{meaning}</div>
      {caution && <div style={{fontSize:23,lineHeight:1.4,marginTop:40,color:colors.muted}}>{caution}</div>}
    </div>
    <div style={{position:'absolute', left:64, top:956, height:3, width:1792, background:colors.line}} />
  </AbsoluteFill>;
};

export const Progress: React.FC = () => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  return <div style={{position:'absolute',left:64,bottom:8,height:3,width:1792*interpolate(frame,[0,durationInFrames-1],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}),background:colors.accent}} />;
};

export const Rules: React.FC = () => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig(); const generation=frame>=10*fps; const t=generation?frame-10*fps:frame;
  const stages=generation?['Qwen','Черновик','Валидация','Проверка автора','Версия банка']:['Версия формы','Параметры задач','Контроль попытки','Сдача','Разбор результата'];
  return <AbsoluteFill style={{background:colors.bg,color:'white',fontFamily:'FspVideo',padding:'90px 110px'}}>
    <Font />
    <div style={{fontSize:27,color:colors.muted}}>РЕАЛИЗОВАННЫЕ ПРАВИЛА · АНИМИРОВАННАЯ СХЕМА</div>
    <div style={{fontSize:72,fontWeight:700,marginTop:70}}>{generation?'Генератор заданий: контроль автора':'Защита попытки: несколько уровней'}</div>
    <div style={{display:'flex',gap:28,marginTop:85}}>{stages.map((label,i)=>{const p=enter(t,fps,i*11);return <div key={label} style={{width:300,opacity:p,transform:`translateY(${35*(1-p)}px)`}}><div style={{fontSize:55,color:colors.accent}}>0{i+1}</div><div style={{fontSize:31,lineHeight:1.25,marginTop:28,minHeight:90}}>{label}</div><div style={{height:4,background:colors.accent,width:280*p}}/></div>})}</div>
    <div style={{fontSize:35,lineHeight:1.6,marginTop:70}}>{generation?<>Модель предлагает черновик, сервер проверяет структуру.<br/>Автор проверяет задание и принимает решение о публикации.</>:<>Меняются параметры форм; ответы и эталоны скрыты до завершения.<br/>Сервер проверяет события и целостность попытки.</>}</div>
    <div style={{position:'absolute',bottom:90,fontSize:27,color:colors.muted}}>{generation?'Схема локального контура. Сам вызов Qwen не входит в исходную экранную запись.':'Контроль целостности — эвристика. Абсолютное предотвращение списывания не заявляется.'}</div>
  </AbsoluteFill>;
};

export const Outro: React.FC = () => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig(); const stage=frame<8*fps?0:frame<22*fps?1:2;
  const localFrame=frame-(stage===0?0:stage===1?8:22)*fps; const s=enter(localFrame,fps);
  const steps = ['Профиль', 'Оценка', 'Категория', 'Подбор', 'Согласие', 'Контакт'];
  return <AbsoluteFill style={{background:colors.bg,color:'white',fontFamily:'FspVideo',padding:'90px 110px'}}>
    <Font />
    <div style={{fontSize:27,color:colors.muted}}>СТУДИЯ 37 · ФСП · ЛЦТ 2026</div>
    <div style={{height:5, width:1700*s,background:colors.accent,marginTop:40}} />
    {stage===0 ? <>
      <div style={{fontSize:82,fontWeight:700,marginTop:55}}>Весь путь — в одной системе</div>
      <div style={{display:'flex',gap:24,marginTop:95}}>{steps.map((step,i)=>{const p=enter(localFrame,fps,i*9);return <div key={step} style={{width:260,opacity:p,transform:`translateY(${25*(1-p)}px)`}}><div style={{fontSize:52,color:colors.accent}}>0{i+1}</div><div style={{fontSize:31,marginTop:28}}>{step}</div><div style={{height:3,background:colors.line,marginTop:32}}/></div>})}</div>
      <div style={{fontSize:37,lineHeight:1.45,marginTop:85}}>Контакт открывается конкретному работодателю после согласия.<br/>Кандидат может отозвать доступ.</div>
    </> : stage===1 ? <>
      <div style={{fontSize:76,fontWeight:700,marginTop:55}}>Исходники доступны публично</div>
      <div style={{fontSize:40,color:'#ff799f',marginTop:32}}>github.com/punkpsyh-hash/Fsp · Public · main</div>
      <div style={{fontSize:36,lineHeight:1.7,marginTop:48}}>01  Открыть публичный репозиторий по ссылке выше.<br/>02  Скачать Code → Download ZIP или выполнить git clone.<br/>03  Использовать ветку main — очищенный конкурсный выпуск.<br/>04  Запустить по README через Docker.</div>
      <div style={{fontSize:26,color:colors.muted,marginTop:40}}>Для просмотра и скачивания не нужны приглашение или аккаунт GitHub.</div>
    </> : <>
      <div style={{fontSize:82,fontWeight:700,marginTop:55}}>Посмотреть. Скачать. Запустить.</div>
      <div style={{fontSize:43,color:'#ff799f',marginTop:50}}>https://fsptest.kolesnikovny.ru</div>
      <div style={{fontSize:35,lineHeight:1.6,marginTop:40}}>Стенд жюри: отдельный пароль от владельца.<br/>Полный локальный запуск: Docker + инструкция в README.<br/>Модель Qwen подключается отдельно; базовый сценарий работает без неё.</div>
      <div style={{fontSize:28,lineHeight:1.5,color:colors.muted,marginTop:48}}>Во внешнем показе отключены регистрация, почта, PDF-импорт и ФСП mock.<br/>Исходная запись: 9 октября. Монтаж и пояснения: 11 октября 2026.<br/>LLM и подключение к официальному ФСП API в этой записи не показаны.</div>
    </>}
  </AbsoluteFill>;
};
