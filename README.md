# Nuki Opener (Bluetooth) для Home Assistant

Локальное управление Nuki Opener по Bluetooth LE, без Nuki Bridge и облака.
Работает через встроенный Bluetooth Home Assistant (или USB-донгл), а также через ESPHome
Bluetooth Proxy с поддержкой активных подключений.

## Установка

### Через магазин приложений (без HACS)

[![Добавить репозиторий](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F42p%2Fha-nuki-opener-ble)

1. *Настройки → Приложения → Магазин приложений → ⋮ → Репозитории*, добавьте
   `https://github.com/42p/ha-nuki-opener-ble`.
2. Установите приложение **Nuki Opener BLE Installer** и нажмите **Запустить** —
   оно скопирует интеграцию в `/config/custom_components` и остановится.
3. Перезапустите Home Assistant.

### Через HACS

HACS → ⋮ → *Custom repositories* → `https://github.com/42p/ha-nuki-opener-ble`, тип **Integration**,
затем установите «Nuki Opener (Bluetooth)» и перезапустите Home Assistant.

### Вручную

Скопируйте `custom_components/nuki_opener_ble` в `/config/custom_components/` и перезапустите Home Assistant.

### Сопряжение

1. Opener найдётся автоматически; если нет — *Настройки → Устройства и службы → Добавить интеграцию → Nuki Opener (Bluetooth)*.
2. Удерживайте кнопку на Opener 5 секунд (режим сопряжения) и нажмите «Подтвердить».

## Возможности

Интеграция делает из Home Assistant замену Nuki Hub / Nuki Bridge для Opener — напрямую через
Bluetooth сервера, без ESP32, MQTT и облака.

| Возможность | Без PIN | С PIN |
|---|:---:|:---:|
| Ring to Open, постоянный режим, открыть дверь | ✅ | ✅ |
| Состояние, режим, источник и результат последнего действия | ✅ | ✅ |
| Батарея (критический заряд, напряжение), уровень сигнала | ✅ | ✅ |
| Событие звонка в домофон (`event.<opener>_doorbell`) | по косвенным признакам | ✅ точно, по журналу Opener |
| Журнал событий (`sensor.<opener>_last_activity`, событие `nuki_opener_ble_log`) | — | ✅ |
| Настройки: LED, кнопка, действия кнопки, таймаут RtO, длительность/задержка открытия, громкость, тип батарей | — | ✅ |
| Синхронизация времени, перезагрузка | — | ✅ |

PIN-код безопасности задаётся в приложении Nuki и вводится в *Настройки интеграции → Настроить*.
Перед сохранением он проверяется на устройстве; при неверном PIN интеграция перестаёт его
использовать, чтобы не заблокировать Opener, и показывает предупреждение в разделе «Ремонт».

### Основные сущности

| Сущность | Описание |
|---|---|
| `lock.<opener>` | заперто = Ring to Open выключен; `unlock` — включить RtO; `open` — открыть дверь |
| `button.<opener>_open_door` | открыть дверь |
| `switch.<opener>_ring_to_open` | Ring to Open |
| `switch.<opener>_continuous_mode` | постоянный режим |
| `event.<opener>_doorbell` | звонок: `ring` — дверь не открывалась, `ring_opened` — открыта по RtO/постоянному режиму |
| `sensor.<opener>_state`, `sensor.<opener>_mode` | состояние и режим Opener |
| `sensor.<opener>_last_ring` | время последнего звонка |

### Автоматизация на звонок

```yaml
triggers:
  - trigger: state
    entity_id: event.nuki_opener_doorbell
actions:
  - action: notify.mobile_app_phone
    data:
      message: "Звонок в домофон"
```

### Как обновляется состояние

Opener в своей Bluetooth-рекламе помечает, что у него изменилось состояние. Интеграция слушает
рекламу без подключения и сразу читает состояние (а с PIN — журнал). Дополнительно состояние
опрашивается по таймеру (по умолчанию раз в 10 минут), батарея и настройки — раз в час.
Интервалы меняются в настройках интеграции.

## Режим «приложение» и режим «мост»

По умолчанию интеграция регистрируется как приложение и занимает один из слотов приложений.
С опцией «Сопрячь как мост» она занимает единственный слот моста: если у вас есть настоящий
Nuki Bridge, его сопряжение будет заменено.
