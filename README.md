# Nuki Opener (Bluetooth) для Home Assistant

Локальное управление Nuki Opener по Bluetooth LE, без Nuki Bridge и облака.
Работает через встроенный Bluetooth Home Assistant, в том числе через ESPHome Bluetooth Proxy
(нужен прокси с поддержкой активных подключений).

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

## Сущности

| Сущность | Описание |
|---|---|
| `lock.<opener>` | заперто = Ring to Open выключен; `unlock` — включить RtO; `open` — открыть дверь |
| `button.<opener>_open_door` | открыть дверь (электрозамок) |
| `switch.<opener>_ring_to_open` | Ring to Open |
| `switch.<opener>_continuous_mode` | постоянный режим (дверь открывается при каждом звонке) |
| `binary_sensor.<opener>_battery` | критический заряд батареи |

Состояние читается каждые 10 минут, а также сразу, как только Opener сообщает в iBeacon-рекламе
об изменении состояния (это происходит без подключения, поэтому батарея почти не расходуется).

## Режим «приложение» и режим «мост»

По умолчанию интеграция регистрируется как приложение и занимает один из слотов приложений.
С опцией «Сопрячь как мост» она занимает единственный слот моста: если у вас есть настоящий
Nuki Bridge, его сопряжение будет заменено.
