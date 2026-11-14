"""Minimal runtime translation for the eyeLens UI.

English is the source language: ``tr()`` receives the English text and returns
the Russian translation when that language is active, or the same text when a
translation is missing.  That keeps partial translations usable.

The persisted setting is ``auto`` (follow Windows), ``en`` or ``ru``.
"""

from __future__ import annotations

import ctypes
import locale
import platform

LANGUAGE_OPTIONS = ("auto", "en", "ru")

_current = "en"


def system_language() -> str:
    """Return ``ru`` or ``en`` for the current Windows UI language."""
    if platform.system() == "Windows":
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Primary language id 0x19 is Russian.
            if lang_id & 0x3FF == 0x19:
                return "ru"
            return "en"
        except Exception:
            pass
    try:
        name = locale.getdefaultlocale()[0] or ""
    except Exception:
        name = ""
    return "ru" if name.lower().startswith("ru") else "en"


def resolve_language(language: str) -> str:
    return system_language() if language == "auto" else ("ru" if language == "ru" else "en")


def set_language(language: str) -> str:
    global _current
    _current = resolve_language(language)
    return _current


def current_language() -> str:
    return _current


def tr(text: str) -> str:
    return _RU.get(text, text) if _current == "ru" else text


_RU: dict[str, str] = {
    # ------------------------------------------------------------ settings
    "A magnifying lens that follows your head": "Лупа, которая следует за головой",
    "Calibrate once before using the lens.": "Откалибруйте линзу перед первым использованием.",
    "Lens": "Линза",
    "Freeze": "Заморозить",
    "Freeze the lens in place so you can move your eyes without moving it "
    "(Ctrl+Alt+F).": "Закрепить линзу на месте, чтобы она не двигалась при "
    "движении глаз (Ctrl+Alt+F).",
    "Fix position": "Исправить позицию",
    "Drag the lens to where you are looking or facing and release; the "
    "model learns that correction (Ctrl+Alt+D).": "Перетащите линзу туда, "
    "куда смотрите, и отпустите — модель запомнит поправку (Ctrl+Alt+D).",
    "Big lens": "Большая линза",
    "Toggle a large lens sized to the screen (Ctrl+Alt+B).": "Включить или "
    "выключить большую линзу по размеру экрана (Ctrl+Alt+B).",
    "Show lens": "Показывать линзу",
    "Head": "Голова",
    "Eyes": "Глаза",
    "Head: move or turn your head to move the lens (recommended). Eyes: "
    "follow your gaze. Switching mode requires recalibration. If no camera "
    "is available, the lens automatically follows the mouse or a finger on "
    "the touchscreen.": "Голова: двигайте или поворачивайте голову, чтобы "
    "перемещать линзу (рекомендуется). Глаза: линза следует за взглядом. "
    "При смене режима нужна повторная калибровка. Если камера недоступна, "
    "линза автоматически следует за мышью или пальцем на сенсорном экране.",
    "Shape": "Форма",
    "Round": "Круглая",
    "Square": "Квадратная",
    "Wide": "Широкая",
    "Lens shape. Wide keeps the chosen height and is 1.6x wider.": "Форма "
    "линзы. Широкая сохраняет выбранную высоту и на 60 % шире.",
    "Size": "Размер",
    "Lens height in pixels; wide lenses are 1.6x wider. Press Ctrl+Alt+B "
    "for a quick big lens.": "Высота линзы в пикселях; широкая линза на 60 % "
    "шире. Ctrl+Alt+B — быстрая большая линза.",
    "Zoom": "Увеличение",
    "Magnification of the area under the lens.": "Кратность увеличения "
    "области под линзой.",
    "Smoothing": "Сглаживание",
    "Higher = calmer, slower lens movement; lower = faster but more jitter.":
    "Больше — плавнее и медленнее; меньше — быстрее, но с дрожанием.",
    "Opacity": "Непрозрачность",
    "Lens opacity.": "Непрозрачность линзы.",
    "Outline": "Обводка",
    "On-screen HUD": "Подсказки на экране",
    "Reset trim": "Сбросить сдвиг",
    "Clear the manual Ctrl+Alt+wheel position trim (Ctrl+Alt+0).": "Сбросить "
    "ручной сдвиг позиции Ctrl+Alt+колесо (Ctrl+Alt+0).",
    "Reset appearance": "Сбросить оформление",
    "Calibrate now": "Калибровать",
    "Recalibrate": "Калибровать заново",
    "Camera": "Камера",
    "Control": "Управление",
    "Calibration": "Калибровка",
    "Webcam index (try 1 if the built-in camera is not 0).": "Номер "
    "веб-камеры (попробуйте 1, если встроенная не 0).",
    "Apply": "Применить",
    "Restart the camera with this index.": "Перезапустить камеру с этим номером.",
    "Hotkeys — work anywhere": "Горячие клавиши — работают везде",
    "Show / hide the lens": "Показать / скрыть линзу",
    "Freeze / unfreeze": "Заморозить / разморозить",
    "Calibrate": "Калибровка",
    "Correct / drag the lens": "Исправить / перетащить линзу",
    "Fine-tune lens position": "Точная подстройка позиции",
    "Reset fine-tune trim": "Сбросить сдвиг",
    "Big lens on / off": "Большая линза вкл. / выкл.",
    "Zoom in / out": "Увеличить / уменьшить масштаб",
    "Grow / shrink lens": "Увеличить / уменьшить линзу",
    "Runs fully offline · webcam stays local": "Работает полностью офлайн · "
    "камера не покидает компьютер",
    "Quit eyeLens": "Выйти из eyeLens",
    "Language": "Язык",
    "System": "Системный",
    "Interface language. System follows the Windows language.": "Язык "
    "интерфейса. «Системный» — язык Windows.",
    "CAMERA": "КАМЕРА",
    "Camera preview": "Предпросмотр камеры",
    "Mouse demo — camera off": "Демо мышью — камера выключена",
    "Camera off": "Камера выключена",
    "Camera error": "Ошибка камеры",
    "Camera stopped": "Камера остановлена",
    "Starting camera…": "Запуск камеры…",
    "Fast": "Быстро",
    "Balanced": "Баланс",
    "Smooth": "Плавно",
    "Very smooth": "Очень плавно",
    "Magnification: {zoom:.2f}× of the area under the lens.": "Увеличение: "
    "{zoom:.2f}× области под линзой.",
    "Aim your head at 25 dots, then 9 accuracy-check dots (about 45 "
    "seconds). Turn or move your head until you are facing each dot, then "
    "hold still. eyeLens learns how your head maps to this screen and reports "
    "the error it measured. Your camera feed never leaves this computer.":
    "Направьте голову на 25 точек, затем на 9 контрольных (около 45 секунд). "
    "Поворачивайте или наклоняйте голову к каждой точке и замирайте. eyeLens "
    "запоминает, как положение головы соотносится с экраном, и показывает "
    "измеренную погрешность. Видео с камеры не покидает компьютер.",
    "Look at 25 dots, then 9 accuracy-check dots (about 80 seconds). For each "
    "dot, hold still for a moment, then slowly move your head left and right "
    "while keeping your eyes on it. eyeLens learns how your eyes map to this "
    "screen, including head-position changes, and reports the error it "
    "measured. Your camera feed never leaves this computer.": "Смотрите на 25 "
    "точек, затем на 9 контрольных (около 80 секунд). На каждой точке замрите, "
    "затем медленно двигайте головой влево-вправо, не отводя глаз. eyeLens "
    "запоминает, как взгляд соотносится с экраном, с учётом положения головы, "
    "и показывает измеренную погрешность. Видео с камеры не покидает компьютер.",

    # -------------------------------------------------------------- app status
    "Mouse demo": "Демо мышью",
    "Mouse pointer": "Мышь",
    "Demo mode": "Демо-режим",
    "Demo mode: the lens follows the mouse. Start without --demo to use head "
    "tracking.": "Демо-режим: линза следует за мышью. Запустите без --demo, "
    "чтобы включить управление головой.",
    "Not calibrated": "Не откалибровано",
    "Unavailable": "Недоступна",
    "Starting…": "Запуск…",
    "Running · {fps:.0f} fps": "Работает · {fps:.0f} кадр/с",
    "Running": "Работает",
    "Mouse / touch": "Мышь / касание",
    "Pointer mode": "Режим мыши",
    "The camera is available, but head tracking needs a calibration. Move the "
    "lens with the mouse or a finger on the touchscreen, or calibrate now.":
    "Камера доступна, но для слежения за головой нужна калибровка. Двигайте "
    "линзу мышью или пальцем по сенсорному экрану либо откалибруйте сейчас.",
    "Camera tracking is unavailable. Move the lens with the mouse or a finger "
    "on the touchscreen. Use Settings → Apply to retry the camera; head "
    "tracking resumes when it is ready.": "Слежение камерой недоступно. "
    "Двигайте линзу мышью или пальцем по сенсорному экрану. Нажмите "
    "«Применить» в настройках, чтобы повторить попытку; слежение за головой "
    "возобновится, когда камера будет готова.",
    "Tracking": "Слежение",
    "Head tracking": "Слежение за головой",
    "Eye tracking": "Слежение за глазами",
    "Face not found": "Лицо не найдено",
    "Eyes closed": "Глаза закрыты",
    "Reacquiring…": "Восстановление…",
    "Estimated accuracy": "Оценочная точность",
    "Initial accuracy": "Начальная точность",
    "Accuracy": "Точность",
    "{count} fix": "поправок: {count}",
    "{count} fixes": "поправок: {count}",
    "head pose": "поза головы",
    "head control": "управление головой",
    "eye control": "управление глазами",
    "Head control": "Управление головой",
    "Eye control": "Управление глазами",
    "{mode} · {label} ±{rmse:.0f} px · {points} points · {samples} samples.":
    "{mode} · {label} ±{rmse:.0f} px · точек: {points} · отсчётов: {samples}.",
    " Calibrated with camera {camera}; recalibrate if accuracy drops.":
    " Калибровка выполнена камерой {camera}; откалибруйте заново, если "
    "точность упадёт.",
    " Trim {x:+d}, {y:+d} px.": " Сдвиг {x:+d}, {y:+d} px.",
    "The display, screen layout, or control mode changed. Calibrate again for "
    "the current setup.": "Изменился экран, расположение мониторов или режим "
    "управления. Откалибруйте заново для текущей конфигурации.",
    "Aim your head at 25 dots plus 9 accuracy-check dots for about 45 "
    "seconds. Turn or move your head to face each dot, then hold still. "
    "eyeLens learns how your head maps to this screen.": "Направьте голову на "
    "25 точек и 9 контрольных — около 45 секунд. Поворачивайте или наклоняйте "
    "голову к каждой точке и замирайте. eyeLens запоминает, как положение "
    "головы соотносится с экраном.",
    "Look at 25 dots plus 9 accuracy-check dots for about 80 seconds. Hold "
    "still, then slowly move your head left and right on each dot so eyeLens "
    "learns head-position compensation.": "Смотрите на 25 точек и 9 "
    "контрольных — около 80 секунд. Замрите, затем медленно двигайте головой "
    "влево-вправо на каждой точке, чтобы eyeLens учитывал положение головы.",
    "Calibrate first": "Сначала калибровка",
    "Calibrate eyeLens before showing the lens.": "Откалибруйте eyeLens перед "
    "показом линзы.",
    "The freeze control needs a calibrated lens.": "Для заморозки нужна "
    "откалиброванная линза.",
    "The size control needs a calibrated lens.": "Для изменения размера нужна "
    "откалиброванная линза.",
    "Lens on": "Линза включена",
    "Lens already {size}": "Линза уже {size}",
    "Correction is unavailable in mouse demo mode.": "Поправка недоступна в "
    "демо-режиме мыши.",
    "Pointer control": "Управление мышью",
    "The lens already follows the mouse or finger exactly; no correction is "
    "needed while the camera is unavailable.": "Линза уже точно следует за "
    "мышью или пальцем; пока камера недоступна, поправка не нужна.",
    "Calibrate eyeLens before correcting it.": "Откалибруйте eyeLens перед "
    "исправлением позиции.",
    "Calibration running": "Идёт калибровка",
    "Finish the current calibration before correcting the lens.": "Завершите "
    "текущую калибровку, прежде чем исправлять линзу.",
    "Still learning": "Ещё обучается",
    "Wait a moment for the previous correction to finish.": "Подождите, пока "
    "завершится предыдущая поправка.",
    "Camera unavailable": "Камера недоступна",
    "The camera is not running.": "Камера не работает.",
    "Camera starting": "Камера запускается",
    "Wait a moment for the camera, then try again.": "Подождите немного, пока "
    "камера запустится, и повторите.",
    "Wait a moment for the camera to start.": "Подождите немного, пока камера "
    "запустится.",
    "The webcam is still starting. Try again in a moment.": "Веб-камера ещё "
    "запускается. Повторите через мгновение.",
    "Correction unavailable": "Поправка недоступна",
    "The lens is busy.": "Линза занята.",
    "Correct lens position": "Исправление позиции линзы",
    "Drag the handle to where you are looking, then release. The lens learns "
    "that spot.": "Перетащите маркер туда, куда смотрите, и отпустите. Линза "
    "запомнит это место.",
    "Correction not learned": "Поправка не запомнена",
    "Keep your face visible and your head facing the lens, then try again.":
    "Держите лицо в кадре и смотрите в сторону линзы, затем повторите.",
    "Keep your face visible and your eyes on the lens, then try again.":
    "Держите лицо в кадре, не отводя глаз от линзы, затем повторите.",
    "Correction failed": "Ошибка поправки",
    "Could not save correction": "Не удалось сохранить поправку",
    "Correction learned": "Поправка запомнена",
    "The lens learned this spot. Press Ctrl+Alt+D again for another area.":
    "Линза запомнила это место. Нажмите Ctrl+Alt+D ещё раз для другой области.",
    "Trim  {x:+d}, {y:+d} px": "Сдвиг  {x:+d}, {y:+d} px",
    "Lens trim reset": "Сдвиг линзы сброшен",
    "Calibration is unavailable in mouse demo mode.": "Калибровка недоступна в "
    "демо-режиме мыши.",
    "Tracking model missing": "Нет модели слежения",
    "Restart eyeLens so it can download the face tracking model.":
    "Перезапустите eyeLens, чтобы загрузить модель отслеживания лица.",
    "Calibration error": "Ошибка калибровки",
    "Could not save calibration": "Не удалось сохранить калибровку",
    "Calibrated · ±{rmse:.0f} px": "Калибровка · ±{rmse:.0f} px",
    "Calibration complete": "Калибровка завершена",
    "Accuracy: ±{rmse:.0f} px. The lens now follows your head.": "Точность: "
    "±{rmse:.0f} px. Линза теперь следует за головой.",
    "Accuracy: ±{rmse:.0f} px. The lens now follows your eyes.": "Точность: "
    "±{rmse:.0f} px. Линза теперь следует за глазами.",
    "Pointer control · no camera": "Управление мышью · нет камеры",
    "Pointer control enabled": "Управление мышью включено",
    "The camera stopped before it became ready.": "Камера остановилась до "
    "готовности.",
    "The camera did not become ready in time.": "Камера не успела запуститься.",
    "Camera ready": "Камера готова",
    "Camera tracking resumed. The lens follows your head again.": "Слежение "
    "камерой возобновлено. Линза снова следует за головой.",
    "Camera tracking resumed. The lens follows your eyes again.": "Слежение "
    "камерой возобновлено. Линза снова следует за глазами.",
    "Camera restarted": "Камера перезапущена",
    "Using camera {index}.": "Используется камера {index}.",
    "Display changed": "Экран изменился",
    "Recalibrate eyeLens for the new display layout.": "Откалибруйте eyeLens "
    "для новой конфигурации экрана.",
    "Main display changed": "Сменился основной экран",
    "Restart eyeLens to use the new primary display.": "Перезапустите eyeLens, "
    "чтобы использовать новый основной экран.",
    "Recalibrate for head control": "Откалибруйте управление головой",
    "Recalibrate for eye control": "Откалибруйте управление глазами",
    "The saved calibration was made for the other control mode. Run "
    "calibration again to use head control.": "Сохранённая калибровка сделана "
    "для другого режима. Пройдите калибровку заново для управления головой.",
    "The saved calibration was made for the other control mode. Run "
    "calibration again to use eye control.": "Сохранённая калибровка сделана "
    "для другого режима. Пройдите калибровку заново для управления глазами.",
    "eyeLens is still running": "eyeLens всё ещё работает",
    "Use the tray icon or Ctrl+Alt+L to show the lens.": "Используйте значок "
    "в трее или Ctrl+Alt+L, чтобы показать линзу.",
    "eyeLens is running": "eyeLens работает",
    "Ctrl+Alt+L shows or hides the lens. Find eyeLens in the tray.":
    "Ctrl+Alt+L показывает и скрывает линзу. eyeLens находится в трее.",
    "Calibrate…": "Калибровать…",
    "Open eyeLens": "Открыть eyeLens",
    "Freeze lens": "Заморозить линзу",
    "Correct lens position…": "Исправить позицию линзы…",
    "Zoom in": "Приблизить",
    "Zoom out": "Отдалить",
    "Larger lens": "Увеличить линзу",
    "Smaller lens": "Уменьшить линзу",

    # ------------------------------------------------------------------ overlay
    "Lens locked": "Линза закреплена",
    "Lens follows the pointer": "Линза следует за мышью",
    "Lens follows your head": "Линза следует за головой",
    "Lens follows your gaze": "Линза следует за взглядом",
    "Drag the handle to where you are looking": "Перетащите маркер туда, куда "
    "смотрите",
    "Correction cancelled": "Поправка отменена",
    "Keep facing the lens…": "Продолжайте смотреть в сторону линзы…",
    "Hold your gaze on the lens…": "Не отводите взгляд от линзы…",
    "Drag to where you are looking, then release": "Перетащите туда, куда "
    "смотрите, и отпустите",

    # -------------------------------------------------------------- calibration
    "eyeLens head calibration": "Калибровка eyeLens: голова",
    "eyeLens eye calibration": "Калибровка eyeLens: глаза",
    "Head moved — return to your starting head position.": "Голова "
    "сместилась — вернитесь в исходное положение.",
    "Calibration complete — this is the accuracy it measured.": "Калибровка "
    "завершена — измеренная точность.",
    "Finishing your calibration…": "Завершаем калибровку…",
    "Building your personal head model…": "Строим вашу модель головы…",
    "Building your personal gaze model…": "Строим вашу модель взгляда…",
    "Accuracy check — aim your head at each dot and hold still.": "Проверка "
    "точности — направьте голову на каждую точку и замрите.",
    "Accuracy check — look at each dot with your eyes only.": "Проверка "
    "точности — смотрите на каждую точку только глазами.",
    "Turn or move your head to face the highlighted dot, then hold still.":
    "Поверните или наклоните голову к подсвеченной точке и замрите.",
    "Hold still, then slowly move your head left and right while keeping your "
    "eyes on the dot.": "Замрите, затем медленно двигайте головой "
    "влево-вправо, не отводя глаз от точки.",
    "check {current} / {total}": "проверка {current} / {total}",
    "Face detected": "Лицо найдено",
    "Hold your head still — sampling this position…": "Держите голову "
    "неподвижно — запись позиции…",
    "Aim your head at the highlighted dot…": "Направьте голову на "
    "подсвеченную точку…",
    "Hold your gaze — sampling stable position…": "Не отводите взгляд — "
    "запись позиции…",
    "Keep your eyes on the dot — slowly move your head left and right…":
    "Смотрите на точку — медленно двигайте головой влево-вправо…",
    "Look at the highlighted dot…": "Смотрите на подсвеченную точку…",
    "Accuracy check · ": "Проверка точности · ",
    "Head moved — return to your starting head position": "Голова "
    "сместилась — вернитесь в исходное положение",
    "   ·   Esc to cancel": "   ·   Esc — отмена",
    "Esc to cancel": "Esc — отмена",
    "camera preview": "предпросмотр камеры",
    "FACE": "ЛИЦО",
    "EYES": "ГЛАЗА",
    "Ready when you are": "Можно начинать",
    "Sit at a comfortable distance from the screen. Your face should be well "
    "lit and fully visible in the camera preview. You will aim your head at 25 "
    "dots, then 9 accuracy-check dots (about 45 seconds). Turn or move your "
    "head until you are facing each dot, then hold still for a moment. Your "
    "eyes are not used for control. Calibration starts automatically once your "
    "face is detected.": "Сядьте удобно перед экраном. Лицо должно быть хорошо "
    "освещено и полностью видно в камере. Вы направите голову на 25 точек, "
    "затем на 9 контрольных (около 45 секунд). Поворачивайте или наклоняйте "
    "голову к каждой точке и замирайте на мгновение. Глаза для управления не "
    "используются. Калибровка начнётся автоматически, когда камера увидит лицо.",
    "Sit at a comfortable distance from the screen. Your face should be well "
    "lit and fully visible in the camera preview. You will look at 25 dots, "
    "then 9 accuracy-check dots (about 80 seconds). For each dot, hold still "
    "for a moment, then slowly move your head a little left and right while "
    "keeping your eyes on it. This teaches head-position compensation. "
    "Calibration starts automatically once your face is detected.": "Сядьте "
    "удобно перед экраном. Лицо должно быть хорошо освещено и полностью видно "
    "в камере. Вы посмотрите на 25 точек, затем на 9 контрольных (около 80 "
    "секунд). На каждой точке замрите, затем медленно двигайте головой немного "
    "влево-вправо, не отводя глаз. Так eyeLens учитывает положение головы. "
    "Калибровка начнётся автоматически, когда камера увидит лицо.",
    "Press Space to begin now": "Нажмите пробел, чтобы начать",
    "Waiting for your face…": "Ждём ваше лицо…",
    "Get comfortable and keep your face in view": "Устройтесь удобно, лицо "
    "должно быть в кадре",
    "Get comfortable and keep looking at the screen": "Устройтесь удобно и "
    "смотрите на экран",
    "Accuracy check — aim your head at each dot": "Проверка точности — "
    "направьте голову на каждую точку",
    "Accuracy check — keep looking at the screen": "Проверка точности — "
    "продолжайте смотреть на экран",
    "Head moved — return to your starting head position and keep still. "
    "Trying this point again…": "Голова сместилась — вернитесь в исходное "
    "положение и замрите. Пробуем эту точку ещё раз…",
    "Hold still — I lost your face. Trying this point again…": "Не "
    "двигайтесь — лицо потеряно. Пробуем эту точку ещё раз…",
    "Not enough steady samples. Trying this point again…": "Мало стабильных "
    "отсчётов. Пробуем эту точку ещё раз…",
    "Head tracking was not stable enough. Improve the lighting and make sure "
    "your face is fully visible.": "Слежение за головой было недостаточно "
    "стабильным. Улучшите освещение и убедитесь, что лицо полностью видно.",
    "Eye tracking was not stable enough. Improve the lighting, keep your head "
    "still, and make sure your face is fully visible.": "Слежение за глазами "
    "было недостаточно стабильным. Улучшите освещение, держите голову "
    "неподвижно и убедитесь, что лицо полностью видно.",
    "Could not build the calibration model: {exc}": "Не удалось построить "
    "модель калибровки: {exc}",
    "Trying again…": "Пробуем ещё раз…",
    "Checking accuracy on independent points…": "Проверяем точность на "
    "независимых точках…",
    "Excellent": "Отлично",
    "Good": "Хорошо",
    "Fair": "Средне",
    "Needs recalibration": "Нужна повторная калибровка",
    "Checked on {points} held-out points (head-pose corrected)": "Проверено "
    "на {points} контрольных точках (с коррекцией позы головы)",
    "Checked on {points} independent points": "Проверено на {points} "
    "независимых точках",
    "Estimated across the whole screen": "Оценка по всему экрану",
    "Turn your head toward each dot and hold still for a sharper lens.":
    "Поворачивайте голову к каждой точке и замирайте — так линза будет точнее.",
    "Try again with better lighting and a still head for a sharper lens.":
    "Попробуйте ещё раз при лучшем освещении и с неподвижной головой — так "
    "линза будет точнее.",
    "You can improve it any time by calibrating again.": "Точность можно "
    "улучшить повторной калибровкой.",
    "{where} ({points} points, {samples} samples). {advice}": "{where}. "
    "Точек: {points}, отсчётов: {samples}. {advice}",
    "Enter  —  use this calibration": "Enter  —  использовать калибровку",
    "R  —  try again": "R  —  повторить",
    "R — start over    ·    Esc — cancel": "R — начать заново    ·    "
    "Esc — отмена",
    "Esc — cancel": "Esc — отмена",
    "Calibration needs another try": "Калибровку нужно повторить",
    "Something went wrong.": "Что-то пошло не так.",
    "R — try again    ·    Esc — cancel": "R — повторить    ·    Esc — отмена",

    # ------------------------------------------------------------- tracker/hotkeys
    "Face tracking model is missing. Run scripts/download_model.py or restart "
    "eyeLens with an internet connection.": "Модель отслеживания лица "
    "отсутствует. Запустите scripts/download_model.py или перезапустите "
    "eyeLens с доступом в интернет.",
    "Loading face tracking model…": "Загрузка модели отслеживания лица…",
    "Could not open the webcam. Check Windows camera privacy settings and "
    "whether another app is using it.": "Не удалось открыть веб-камеру. "
    "Проверьте разрешения камеры в Windows и не занята ли она другим "
    "приложением.",
    "Camera running ({camera_label}) — looking for your face…": "Камера "
    "работает ({camera_label}) — ищем лицо…",
    "The webcam stopped delivering frames.": "Веб-камера перестала передавать "
    "кадры.",
    "Tracking your eyes": "Слежение за глазами",
    "Looking for your face…": "Ищем лицо…",
    "Eye tracking stopped unexpectedly. Check the log for details.": "Слежение "
    "неожиданно остановилось. Подробности в журнале.",
    "eyeLens failed to start:\n\n{exc}": "Не удалось запустить eyeLens:\n\n{exc}",
    "Global hotkeys are unavailable: {exc}": "Глобальные горячие клавиши "
    "недоступны: {exc}",
    "Global mouse wheel is unavailable: {exc}": "Глобальное колесо мыши "
    "недоступно: {exc}",
}
