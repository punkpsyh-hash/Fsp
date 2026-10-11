// Создано generate.py из storyboard.json. Клипы и подписи представлены отдельными JSX-узлами.
import React from 'react';
import {AbsoluteFill, Composition, Series, useVideoConfig} from 'remotion';
import {FrameVideo} from './FrameVideo';
import {BasicCaptions} from './basic-captions';
import {Intro, Chapter, Screen, Rules, Outro, Progress} from './Graphics';
const Demo: React.FC = () => {
  const {fps}=useVideoConfig();
  return <AbsoluteFill><Series>
<Series.Sequence name="Вступление" durationInFrames={150} premountFor={fps}><Intro /></Series.Sequence>
<Series.Sequence name={"Профиль кандидата"} durationInFrames={60} premountFor={fps}><Chapter number={"01"} title={"Профиль кандидата"} subtitle={"Регистрация, подтверждение и заполнение анкеты"} /></Series.Sequence>
<Series.Sequence name={"Профиль кандидата · 1"} trimBefore={50} durationInFrames={300} premountFor={fps}>
          <Screen number={"01"} title={"Профиль кандидата"} meaning={"Кандидат задаёт условия поиска и сведения о себе."} caution={"Подтверждение в записи — через локальную mock-почту. Реальная SMTP-доставка здесь не показана."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Начинаем с демонстрационного сценария на синтетических данных.", "startMs": 2000, "endMs": 4000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Создаём тестовый аккаунт и подтверждаем вход через локальную mock-почту.", "startMs": 4000, "endMs": 8000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Заполняем анкету. Заявленные технологии пока не означают подтверждённые навыки.", "startMs": 8000, "endMs": 14000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Оценка навыков"} durationInFrames={60} premountFor={fps}><Chapter number={"02"} title={"Оценка навыков"} subtitle={"Версия формы, сохранение ответов и результат"} /></Series.Sequence>
<Series.Sequence name={"Оценка навыков · 1"} trimBefore={350} durationInFrames={1112} premountFor={fps}>
          <Screen number={"02"} title={"Оценка навыков"} meaning={"Результат теста отделён от заявлений в анкете и от практики работодателя."} caution={"Серверные версии форм и контроль целостности попытки. Правила защиты поясняются в конце ролика."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Начинаем оценку: вопросы последовательно открываются в интерфейсе кандидата.", "startMs": 14000, "endMs": 21000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Отвечаем на задания с кодом. Сохранение позволяет продолжить текущую попытку.", "startMs": 21000, "endMs": 29000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Навигация по вопросам сохраняет ответы в пределах этой попытки.", "startMs": 29000, "endMs": 37000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Продолжаем оценку по серверной версии формы.", "startMs": 37000, "endMs": 45000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Завершаем все 12 вопросов и проверяем ответы перед окончательной отправкой.", "startMs": 45000, "endMs": 52000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "После подтверждения доступен разбор результата и оценка навыков.", "startMs": 52000, "endMs": 58500, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Оценка навыков · 2"} trimBefore={1550} durationInFrames={100} premountFor={fps}>
          <Screen number={"02"} title={"Оценка навыков"} meaning={"Результат теста отделён от заявлений в анкете и от практики работодателя."} caution={"Серверные версии форм и контроль целостности попытки. Правила защиты поясняются в конце ролика."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "История хранит попытку. Видимость своего профиля кандидат настраивает в «Приватности».", "startMs": 62000, "endMs": 66000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Короткие задания"} durationInFrames={60} premountFor={fps}><Chapter number={"03"} title={"Короткие задания"} subtitle={"Практика под конкретную потребность компании"} /></Series.Sequence>
<Series.Sequence name={"Короткие задания · 1"} trimBefore={1650} durationInFrames={150} premountFor={fps}>
          <Screen number={"03"} title={"Короткие задания"} meaning={"Работодатель получает дополнительное свидетельство подхода кандидата к своей задаче."} caution={"Работа над задачей компании сама по себе не повышает глобальный грейд."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Открываем короткое задание компании и отправляем описание своего подхода.", "startMs": 66000, "endMs": 72000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Подбор под задачи"} durationInFrames={60} premountFor={fps}><Chapter number={"04"} title={"Подбор под задачи"} subtitle={"Потребности работодателя, поиск и сравнение"} /></Series.Sequence>
<Series.Sequence name={"Подбор под задачи · 1"} trimBefore={1950} durationInFrames={38} premountFor={fps}>
          <Screen number={"04"} title={"Подбор под задачи"} meaning={"Выдача объясняет соответствие кандидата заданным требованиям работодателя."} caution={"Указанные задачи добавляют желательные навыки, сохраняя жёсткие фильтры поиска."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Работодатель выбирает рабочие задачи и требуемые навыки.", "startMs": 78000, "endMs": 79500, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Подбор под задачи · 2"} trimBefore={2100} durationInFrames={132} premountFor={fps}>
          <Screen number={"04"} title={"Подбор под задачи"} meaning={"Выдача объясняет соответствие кандидата заданным требованиям работодателя."} caution={"Указанные задачи добавляют желательные навыки, сохраняя жёсткие фильтры поиска."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Ищем кандидатов и сравниваем составляющие оценки соответствия.", "startMs": 84000, "endMs": 89300, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Подбор под задачи · 3"} trimBefore={2338} durationInFrames={112} premountFor={fps}>
          <Screen number={"04"} title={"Подбор под задачи"} meaning={"Выдача объясняет соответствие кандидата заданным требованиям работодателя."} caution={"Указанные задачи добавляют желательные навыки, сохраняя жёсткие фильтры поиска."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Формируем персональное предложение: зарплата, условия и сообщение кандидату.", "startMs": 93500, "endMs": 98000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Согласие на контакт"} durationInFrames={60} premountFor={fps}><Chapter number={"05"} title={"Согласие на контакт"} subtitle={"Приглашение, принятие и отзыв доступа"} /></Series.Sequence>
<Series.Sequence name={"Согласие на контакт · 1"} trimBefore={2450} durationInFrames={50} premountFor={fps}>
          <Screen number={"05"} title={"Согласие на контакт"} meaning={"Каждый доступ к контакту связан с конкретным работодателем и решением кандидата."} caution={""}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Предложение появляется у работодателя в разделе отправленных приглашений.", "startMs": 98000, "endMs": 100000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Согласие на контакт · 2"} trimBefore={2600} durationInFrames={783} premountFor={fps}>
          <Screen number={"05"} title={"Согласие на контакт"} meaning={"Каждый доступ к контакту связан с конкретным работодателем и решением кандидата."} caution={""}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Переключаемся в синтетический аккаунт кандидата, чтобы проверить входящее предложение.", "startMs": 104000, "endMs": 113000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Открываем входящие. Просмотр предложения не открывает контакт; нужно отдельное согласие.", "startMs": 113000, "endMs": 118000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "После принятия контакт разрешён только отправителю этого предложения.", "startMs": 118000, "endMs": 122000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "В кабинете работодателя видны статус «Принято» и разрешённый контакт.", "startMs": 122000, "endMs": 128000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Возвращаемся к кандидату и отзываем доступ к контакту в разделе приватности.", "startMs": 128000, "endMs": 135300, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Согласие на контакт · 3"} trimBefore={3458} durationInFrames={192} premountFor={fps}>
          <Screen number={"05"} title={"Согласие на контакт"} meaning={"Каждый доступ к контакту связан с конкретным работодателем и решением кандидата."} caution={""}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Работодатель теперь видит отзыв согласия; контакт становится недоступен.", "startMs": 138300, "endMs": 146000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Отклик на вакансию"} durationInFrames={60} premountFor={fps}><Chapter number={"06"} title={"Отклик на вакансию"} subtitle={"Инициатива кандидата и отзыв отклика"} /></Series.Sequence>
<Series.Sequence name={"Отклик на вакансию · 1"} trimBefore={3650} durationInFrames={875} premountFor={fps}>
          <Screen number={"06"} title={"Отклик на вакансию"} meaning={"Кандидат может сам откликнуться, а затем отозвать отклик и связанный доступ."} caution={""}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Кандидат открывает вакансию и отправляет отклик с разрешением доступа к контакту.", "startMs": 146000, "endMs": 154000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Переключаемся к работодателю: отклик и разрешённый контакт доступны в его кабинете.", "startMs": 154000, "endMs": 163000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Кандидат возвращается в «Мои отклики» и отзывает отправленный отклик.", "startMs": 163000, "endMs": 173000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Проверяем результат у работодателя: отклик отозван, контакт больше недоступен.", "startMs": 173000, "endMs": 181000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Конструктор и импорт"} durationInFrames={60} premountFor={fps}><Chapter number={"07"} title={"Конструктор и импорт"} subtitle={"Авторские задания, предварительный просмотр и версии"} /></Series.Sequence>
<Series.Sequence name={"Конструктор и импорт · 1"} trimBefore={4600} durationInFrames={750} premountFor={fps}>
          <Screen number={"07"} title={"Конструктор и импорт"} meaning={"Автор контролирует содержимое и публикует подготовленный набор заданий."} caution={"В этой записи показаны ручной конструктор и импорт. Генерация Qwen здесь не демонстрируется."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Открываем конструктор и подготавливаем набор с числовым заданием.", "startMs": 184000, "endMs": 191000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Заполняем условие, правильный ответ и навыки; проверяем предварительный просмотр.", "startMs": 191000, "endMs": 199000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Импортируем набор: сначала проверка файла, затем сохранение и публикация версии.", "startMs": 199000, "endMs": 208000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Переключаемся к кандидату и открываем опубликованный практический набор.", "startMs": 208000, "endMs": 214000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Практика в VM"} durationInFrames={60} premountFor={fps}><Chapter number={"08"} title={"Практика в VM"} subtitle={"Python, JavaScript и SQL; результат в профиле"} /></Series.Sequence>
<Series.Sequence name={"Практика в VM · 1"} trimBefore={5350} durationInFrames={1382} premountFor={fps}>
          <Screen number={"08"} title={"Практика в VM"} meaning={"Практический набор проверяет исполняемый ответ, сохраняя источник каждого результата."} caution={"SQL-задача использует SQLite. Практика не подтверждает глобальный Middle автоматически."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "Пишем решение Python и запускаем пример через отдельный VM runner.", "startMs": 214000, "endMs": 222000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Дожидаемся проверки Python. Интерфейс показывает состояние выполнения.", "startMs": 222000, "endMs": 233000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Переходим к JavaScript: вводим решение и запускаем проверку примера.", "startMs": 233000, "endMs": 244000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Ожидаем проверку JavaScript, сохраняем ответ и переходим к SQL.", "startMs": 244000, "endMs": 253000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Выполняем SQL-задание в явно указанном диалекте SQLite.", "startMs": 253000, "endMs": 262000, "timestampMs": null, "confidence": null, "pageBreakAfter": true}, {"text": "Ожидаем SQL-проверку и проверяем ответы перед окончательной сдачей набора.", "startMs": 262000, "endMs": 269300, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name={"Практика в VM · 2"} trimBefore={6800} durationInFrames={112} premountFor={fps}>
          <Screen number={"08"} title={"Практика в VM"} meaning={"Практический набор проверяет исполняемый ответ, сохраняя источник каждого результата."} caution={"SQL-задача использует SQLite. Практика не подтверждает глобальный Middle автоматически."}>
            <FrameVideo style={{position:'absolute',left:64,top:110,width:1328,height:830}} />
            <BasicCaptions name="Пояснение действия" width={3318} combineTokensWithinMilliseconds={0} style={{position:'absolute',left:64,top:965,transform:'scale(0.54)',transformOrigin:'top left'}} captions={[{"text": "После сдачи доступен разбор; практика отдельно сохраняется в профиле.", "startMs": 272000, "endMs": 276500, "timestampMs": null, "confidence": null, "pageBreakAfter": true}]} />
          </Screen>
        </Series.Sequence>
<Series.Sequence name="Защита и генератор: схемы" durationInFrames={500} premountFor={fps}><Rules /></Series.Sequence>
<Series.Sequence name="Итог и доступ жюри" durationInFrames={900} premountFor={fps}><Outro /></Series.Sequence>
</Series><Progress /></AbsoluteFill>;
};
export const Root: React.FC = () => <Composition id="FspDemo" component={Demo} durationInFrames={8118} fps={25} width={1920} height={1080} />;
