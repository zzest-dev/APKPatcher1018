# APKPatcher1018

Автономный патчер оригинального Android APK MadOut2 BigCityOnline **10.18 / 100118 / ARMv7** для подключения к [AccountBackend1018](https://github.com/zzest-dev/AccountBackend1018).

Патчер создаёт отдельное приложение `com.MadOut.BIG.backend1018`. Оригинальная игра может оставаться установленной. Адрес аккаунтного сервера задаётся при патчинге и затем меняется через `backend.txt` на устройстве.

Готовый APK и OBB с нужным именем можно скачать в [Releases](https://github.com/zzest-dev/APKPatcher1018/releases). Готовая сборка сервера доступна в [Releases AccountBackend1018](https://github.com/zzest-dev/AccountBackend1018/releases).

## Требования

- Python **3.11+**, только стандартная библиотека.
- JDK с `java` и `keytool` в PATH или в `JAVA_HOME`.
- Android SDK Build Tools с `zipalign` и `lib/apksigner.jar`. Путь задаётся через `ANDROID_SDK_ROOT`, `ANDROID_HOME`, `--android-sdk` или непосредственно `--build-tools`.
- Оригинальные APK и OBB 10.18, предоставленные пользователем. Эти файлы в репозиторий не включены.

Unity и Android NDK для обычного патчинга не требуются: готовые `payload/classes.dex` и `payload/armeabi-v7a/libbackend1018.so` входят в репозиторий вместе с исходниками и контрольными суммами. Текущий набор проверен с JDK 8 и Android SDK Build Tools 28.0.3 на Windows.

Поддерживается только исходный APK с SHA-256:

```text
2941a49eaf332930580b81bb2e8012b6684e6103031551d176a765b4ed152848
```

ARM64, другие версии и уже модифицированные APK отклоняются. Это проверка совместимости фиксированных IL2CPP-адресов, а не универсальный патчер всех сборок 10.18.

## Запуск

```powershell
$env:JAVA_HOME = 'C:\Android\jdk'
$env:ANDROID_SDK_ROOT = 'C:\Android\sdk'
python patch.py 'C:\Games\original-10.18.apk' --host 192.168.1.10 --port 10118 --output 'C:\Games\patched-10.18.apk'
```

Путь к SDK можно указать явно:

```sh
python patch.py original-10.18.apk --host 192.168.1.10 --android-sdk /path/to/sdk --java-home /path/to/jdk --output patched-10.18.apk
```

`--host` обязателен: это IPv4 ПК с аккаунтным сервером. Порт по умолчанию 10118. Доменные имена и IPv6 пока не поддержаны. Для эмулятора с настроенным ADB reverse допустим `127.0.0.1`.

Патчер не переписывает исходный APK. Существующий выходной файл не заменяется без `--force`. Перед выдачей результата проверяются подписи, выравнивание ZIP, содержимое внедрённых файлов и сохранность остальных оригинальных записей. Рядом сохраняется отчёт `patched-10.18.apk.report.json` с SHA-256, адресом сервера, package name и результатом проверки подписи.

## Подпись

Без `--keystore` создаётся локальный тестовый ключ `.keys/local-test.keystore`, alias `apkpatcher1018`, пароль `android`. Он повторно используется при последующих запусках. Ключ создаётся отдельно на каждом компьютере и не коммитится в Git.

Для выпуска обновлений используйте один постоянный собственный ключ. Установленный Android-клиент принимает обновление только с той же подписью. Старые тестовые APK могут быть подписаны другим ключом; патчер не восстанавливает чужой ключ и не обходит проверку Android.

```powershell
$env:APKPATCHER_STORE_PASS = '<пароль-хранилища>'
$env:APKPATCHER_KEY_PASS = '<пароль-ключа>'
python patch.py original-10.18.apk --host 192.168.1.10 --keystore 'C:\Keys\release.jks' --key-alias release --key-pass-env APKPATCHER_KEY_PASS --output patched-10.18.apk
```

По умолчанию пароль хранилища читается из `APKPATCHER_STORE_PASS`; другое имя задаёт `--store-pass-env`. Если `--key-pass-env` не указан, используется тот же пароль. Пароли передаются инструментам через окружение, не записываются в отчёт и не передаются в открытом виде аргументами командной строки.

## Установка и OBB

```sh
adb install -r patched-10.18.apk
adb shell mkdir -p /sdcard/Android/obb/com.MadOut.BIG.backend1018
adb push main.100118.com.MadOut.BIG.obb /sdcard/Android/obb/com.MadOut.BIG.backend1018/main.100118.com.MadOut.BIG.backend1018.obb
```

OBB копируется без изменения содержимого. Правильный путь:

```text
Android/obb/com.MadOut.BIG.backend1018/main.100118.com.MadOut.BIG.backend1018.obb
```

При первом запуске `BackendActivity` копирует встроенные параметры в:

```text
Android/data/com.MadOut.BIG.backend1018/files/backend.txt
```

```ini
ip=192.168.1.10
port=10118
```

Существующий файл не перезаписывается при обновлении. Измените его и перезапустите игру, чтобы переключиться на другой сервер. Для гостевого аккаунта используйте **Offline or Anonim**; Facebook-вход своим аккаунтным сервером не реализован.

## Что меняется в APK

1. Проверяется SHA-256 оригинального APK и контрольные суммы payload.
2. В бинарном `AndroidManifest.xml` меняются package name, launcher activity, authorities и связанные имена разрешений.
3. В `resources.arsc` меняется только строковое имя пакета таблицы ресурсов.
4. Добавляются `classes4.dex`, `lib/armeabi-v7a/libbackend1018.so` и `assets/backend-defaults.properties`.
5. Удаляются прежние подписи, выполняются zipalign и подпись v1/v2 новым ключом.
6. Все прочие исходные ZIP-записи сравниваются побайтно с оригиналом, включая `libil2cpp.so` и metadata. Изменения проверяются до замены выходного файла.

Java-activity запускает инициализацию в Unity-потоке. Нативная часть проверяет имена и RVA четырёх методов в загруженном `libil2cpp.so`, удерживает managed endpoint через GC handle и устанавливает Dobby-хуки:

| Метод | RVA ARMv7 |
| --- | --- |
| `Client_FindMirror.GetOrCreateLink` | `0x6D58A0` |
| `MyReq..ctor` с пятью параметрами | `0xA03100` |
| `Client_FindMirror.Update` | `0x6D61E4` |
| `Client_FindMirror.LoadFromSite` | `0x6D68B4` |

Выбор зеркала и адрес аккаунтных запросов перенаправляются на `backend.txt`, используется штатный TCP-кодек. 

## Пересборка payload из исходников

Нужны Python 3.11+, CMake, Ninja, JDK, Android SDK с platform `android-28`, Build Tools 28.0.3 и Android NDK r16b. Это проверенный набор для текущего Dobby. Более новые NDK здесь не заявлены как проверенные.

```sh
python tools/build_payload.py --android-sdk /path/to/sdk --ndk /path/to/android-ndk-r16b --java-home /path/to/jdk
```

Пути к CMake/Ninja переопределяются через `--cmake` и `--ninja`, номер SDK platform через `--android-api`. Скрипт собирает C++/Java, обновляет оба файла `payload` и `payload/manifest.json`.

`compile-stubs/` содержит минимальные декларации Unity-классов для компиляции. Они не входят в DEX; настоящие классы используются из оригинального APK. Благодаря этому не требуется распространять Unity `classes.jar`.

`vendor/Dobby` — исходники [Dobby](https://github.com/jmpews/Dobby/tree/2b988dc976f9f8630c6ce8d87aaa9f0deb21bbba), коммит `2b988dc976f9f8630c6ce8d87aaa9f0deb21bbba`, Apache 2.0. Сохранено локальное исправление инициализации `thumb_mode = false` в `source/InterceptEntry.cpp`. Лицензия находится в `vendor/Dobby/LICENSE`.

## Проверки

```sh
python -m unittest discover -s tests -v
```

Дополнительные проверки на настоящем оригинальном APK:

```powershell
$env:ORIGINAL_APK_1018 = 'C:\Games\original-10.18.apk'
python -m unittest discover -s tests -v
```

Обычные проверки не требуют SDK, JDK или самого APK. Полный запуск патчера дополнительно проверяет zipalign и apksigner. Проверки сохранности файлов и подписи не заменяют проверку запуска на устройстве. Аккаунтные хуки происходят из ранее проверенного клиента; поставляемая упрощённая Java-activity должна также проверяться на целевых Android-устройствах.
