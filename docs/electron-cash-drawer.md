# Electron 에서 금전함 열기 (ESC/POS)

`pos_tester` 의 금전함 제어 로직을 Electron 앱에 옮기기 위한 문서입니다.
바이트 정의와 판정 로직은 `pos_tester/core/escpos.py`, `pos_tester/core/tester.py` 와 동일합니다.

---

## 1. 먼저 알아야 할 것

**금전함은 POS 에 직접 붙지 않습니다.** 프린터의 DK(Drawer Kick) 포트를 경유합니다.

```
Electron 앱  ──(시리얼 또는 USB)──▶  영수증 프린터  ──(RJ-11/RJ-12)──▶  금전함
```

그래서 **프린터에 바이트를 보내는 방법만 있으면** 금전함도 열립니다.
금전함용 별도 드라이버나 SDK 는 필요 없습니다.

### DK 커넥터 핀 배치

| 핀 | 역할 |
|---|---|
| 1 | 프레임 GND |
| **2** | **솔레노이드 구동 신호 1** |
| **3** | **서랍 열림 감지 스위치 입력** |
| 4 | +12V / +24V |
| **5** | **솔레노이드 구동 신호 2** |
| 6 | 신호 GND |

**여는 회선(2·5번)과 감지 회선(3번)은 완전히 별개입니다.**
2번과 5번 중 어느 쪽에 배선됐는지는 기종마다 다르므로 **둘 다 시도해야 합니다.**

---

## 2. 보낼 바이트

| 동작 | 바이트 | 설명 |
|---|---|---|
| 금전함 열기 (2번 핀) | `1B 70 00 19 FA` | `ESC p 0 25 250` — on 50ms / off 500ms |
| 금전함 열기 (5번 핀) | `1B 70 01 19 FA` | `ESC p 1 25 250` |
| 금전함 열기 (리얼타임) | `10 14 01 00 02` | `DLE DC4` — 출력 버퍼를 무시하고 즉시 동작 |
| 프린터 상태 조회 | `10 04 01` | `DLE EOT 1` — 응답 1바이트, **시리얼에서만 가능** |

`ESC p` 의 시간 인자는 **2ms 단위**입니다. `0x19` = 25 = 50ms, `0xFA` = 250 = 500ms.
`DLE DC4` 의 시간 인자는 **100ms 단위**(1~8)입니다.

> **리얼타임 킥을 언제 쓰나**
> 프린터가 용지 없음 등으로 멈춰 출력 버퍼가 밀려 있으면 `ESC p` 는 버퍼 뒤에서 대기합니다.
> `DLE DC4` 는 버퍼를 건너뛰고 즉시 실행되므로, 급할 때 대안으로 노출해 두면 좋습니다.

### escpos.js

```js
// escpos.js — 명령 바이트 생성. 하드웨어·UI 의존성 없음.
const ESC = 0x1b;
const GS  = 0x1d;
const DLE = 0x10;
const EOT = 0x04;
const DC4 = 0x14;

export const DrawerPin = Object.freeze({ PIN_2: 0, PIN_5: 1 });
export const CutMode  = Object.freeze({ FULL: 0, PARTIAL: 1 });

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** ESC p m t1 t2 — 시간 단위는 2ms. */
export function drawerKick(pin = DrawerPin.PIN_2, onMs = 50, offMs = 500) {
  const ticks = (ms) => clamp(Math.round(ms / 2), 0, 255);
  return Buffer.from([ESC, 0x70, pin, ticks(onMs), ticks(offMs)]);
}

/** DLE DC4 n m t — 출력 버퍼를 무시하는 리얼타임 킥. 시간 단위는 100ms(1~8). */
export function drawerKickRealtime(pin = DrawerPin.PIN_2, onMs = 200) {
  return Buffer.from([DLE, DC4, 0x01, pin, clamp(Math.round(onMs / 100), 1, 8)]);
}

/** DLE EOT n — 리얼타임 상태 조회 (n = 1~4). */
export function statusQuery(n = 1) {
  return Buffer.from([DLE, EOT, n]);
}

export const initialize = () => Buffer.from([ESC, 0x40]);          // ESC @
export const feedAndCut = (lines = 3, mode = CutMode.FULL) =>      // GS V B/C n
  Buffer.from([GS, 0x56, mode === CutMode.FULL ? 0x42 : 0x43, clamp(lines, 0, 255)]);

// ── 상태 바이트 해석 ───────────────────────────────────────────────
const PIN3_BIT = 0x04;

/**
 * DLE EOT 응답은 bit0=0, bit1=1, bit4=1, bit7=0 이 고정이다.
 * 이걸 만족하지 않으면 통신 속도가 안 맞아 깨진 바이트다.
 */
export function isValidStatusByte(b) {
  return (b & 0b1001_0011) === 0b0001_0010;
}

/**
 * 금전함 커넥터 3번 핀이 HIGH 인지.
 *
 * 주의: 어느 레벨이 '열림'인지는 ESC/POS 규격이 정하지 않는다.
 * 금전함 스위치가 NO 냐 NC 냐에 따라 반대가 되므로,
 * 이 값 하나로 열림을 판정하면 안 된다. (4장 참고)
 */
export function pin3High(statusByte) {
  return (statusByte & PIN3_BIT) !== 0;
}
```

---

## 3. 프린터에 바이트 보내기

Electron 은 **메인 프로세스(Node.js)** 에서만 하드웨어에 접근합니다.
렌더러는 IPC 로 요청만 보냅니다.

### 방법 A — 시리얼 (COM). 권장

양방향이라 상태 조회가 되고, 그래야 **실제로 열렸는지 확인**할 수 있습니다.

```bash
npm i serialport
```

```js
// transport-serial.js
import { SerialPort } from 'serialport';

export class SerialTransport {
  /** @param {{path: string, baudRate?: number, rtscts?: boolean}} opts */
  constructor({ path, baudRate = 38400, rtscts = false }) {
    this.supportsRead = true;
    this.displayName = `${path} · ${baudRate} · 8N1`;
    this.port = new SerialPort({
      path,
      baudRate,
      dataBits: 8,
      parity: 'none',
      stopBits: 1,
      rtscts,
      autoOpen: false,
    });
  }

  open() {
    return new Promise((resolve, reject) =>
      this.port.open((err) => (err ? reject(new Error(`${this.displayName} 포트를 열 수 없습니다. ${err.message}`)) : resolve())),
    );
  }

  close() {
    return new Promise((resolve) => this.port.close(() => resolve()));
  }

  write(buffer) {
    return new Promise((resolve, reject) => {
      this.port.write(buffer, (err) => {
        if (err) return reject(new Error(`데이터를 보내지 못했습니다. ${err.message}`));
        this.port.drain((drainErr) => (drainErr ? reject(drainErr) : resolve()));
      });
    });
  }

  /** 명령을 보내고 응답 1바이트를 기다린다. 잔여 응답이 섞이지 않게 버퍼를 비우고 시작한다. */
  query(command, timeoutMs = 1000) {
    return new Promise((resolve, reject) => {
      this.port.flush(() => {
        const timer = setTimeout(() => {
          this.port.off('data', onData);
          reject(new Error(
            '프린터가 응답하지 않습니다. ' +
            '통신 속도(baud)가 다르거나, 크로스 케이블이 필요하거나, 흐름 제어 설정이 다를 수 있습니다.',
          ));
        }, timeoutMs);

        const onData = (chunk) => {
          clearTimeout(timer);
          this.port.off('data', onData);
          resolve(chunk[0]);
        };

        this.port.once('data', onData);
        this.port.write(command, (err) => {
          if (err) {
            clearTimeout(timer);
            this.port.off('data', onData);
            reject(err);
          }
        });
      });
    });
  }
}
```

포트 목록:

```js
import { SerialPort } from 'serialport';
const ports = await SerialPort.list();   // [{ path: 'COM3', manufacturer: '...' }, ...]
```

> **네이티브 모듈 주의**
> `serialport` 는 네이티브 모듈이라 Electron 의 ABI 에 맞춰 다시 빌드해야 합니다.
> `electron-builder` 를 쓰면 `npx electron-builder install-app-deps` 가 처리해 줍니다.
> 그게 번거로우면 아래 **방법 C(Web Serial)** 를 쓰면 네이티브 모듈이 아예 필요 없습니다.

### 방법 B — USB (Windows 스풀러 RAW)

프린터가 USB 로 붙어 윈도우 프린터로 잡혀 있을 때입니다.
**단방향입니다.** 보내는 건 되지만 상태는 못 읽습니다 → **열렸는지 확인할 수 없습니다.**

Node 에는 `win32print` 같은 게 없습니다. 네이티브 모듈(`@thiagoelg/node-printer`) 은
빌드가 자주 깨지므로, **PowerShell 로 `winspool.drv` 를 직접 부르는 방식**을 권합니다.
추가 의존성이 없고 파이썬판이 하는 일과 똑같습니다.

```js
// transport-winspool.js
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { writeFile, unlink, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const execFileAsync = promisify(execFile);

// StartDocPrinter 의 datatype 을 "RAW" 로 지정해야 드라이버가 가공하지 않고 그대로 보낸다.
const PS_SCRIPT = `
param([Parameter(Mandatory)][string]$PrinterName,[Parameter(Mandatory)][string]$FilePath)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class RawPrinter {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public class DOCINFOW {
    [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
    [MarshalAs(UnmanagedType.LPWStr)] public string pOutputFile;
    [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
  }
  [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool OpenPrinter(string src, out IntPtr h, IntPtr pd);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool ClosePrinter(IntPtr h);
  [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool StartDocPrinter(IntPtr h, int level, [In, MarshalAs(UnmanagedType.LPStruct)] DOCINFOW di);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool EndDocPrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool StartPagePrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool EndPagePrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)]
  static extern bool WritePrinter(IntPtr h, IntPtr buf, int count, out int written);

  public static void Send(string printerName, byte[] bytes) {
    IntPtr h;
    if (!OpenPrinter(printerName, out h, IntPtr.Zero))
      throw new Exception("OpenPrinter 실패 (" + Marshal.GetLastWin32Error() + ")");
    try {
      var di = new DOCINFOW { pDocName = "POS RAW", pDataType = "RAW" };
      if (!StartDocPrinter(h, 1, di))
        throw new Exception("StartDocPrinter 실패 (" + Marshal.GetLastWin32Error() + ")");
      try {
        StartPagePrinter(h);
        IntPtr p = Marshal.AllocCoTaskMem(bytes.Length);
        try {
          Marshal.Copy(bytes, 0, p, bytes.Length);
          int written;
          if (!WritePrinter(h, p, bytes.Length, out written))
            throw new Exception("WritePrinter 실패 (" + Marshal.GetLastWin32Error() + ")");
        } finally { Marshal.FreeCoTaskMem(p); }
        EndPagePrinter(h);
      } finally { EndDocPrinter(h); }
    } finally { ClosePrinter(h); }
  }
}
'@
[RawPrinter]::Send($PrinterName, [System.IO.File]::ReadAllBytes($FilePath))
`;

export class WinSpoolerTransport {
  constructor(printerName) {
    this.printerName = printerName;
    this.supportsRead = false;                       // 단방향
    this.displayName = `${printerName} (USB · 단방향)`;
  }

  async open() {}
  async close() {}

  async write(buffer) {
    const dir = await mkdtemp(path.join(tmpdir(), 'posraw-'));
    const file = path.join(dir, 'payload.bin');
    await writeFile(file, buffer);
    try {
      await execFileAsync('powershell.exe', [
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-Command', PS_SCRIPT,
        '-PrinterName', this.printerName,
        '-FilePath', file,
      ]);
    } catch (err) {
      throw new Error(`프린터로 데이터를 보내지 못했습니다. ${err.stderr || err.message}`);
    } finally {
      await unlink(file).catch(() => {});
    }
  }

  async query() {
    throw new Error(
      'USB(윈도우 스풀러) 연결은 단방향이라 프린터 상태를 읽을 수 없습니다. ' +
      '상태 확인이 필요하면 시리얼(COM)로 연결하세요.',
    );
  }
}
```

프린터 목록은 Electron 이 기본 제공합니다:

```js
const printers = await mainWindow.webContents.getPrintersAsync();
// [{ name, displayName, isDefault, ... }]
```

### 방법 C — Web Serial (네이티브 모듈 없이)

Electron 은 렌더러에서 `navigator.serial` 을 지원합니다. 네이티브 빌드가 필요 없습니다.
다만 **권한 핸들러를 메인에서 붙여야** 하고, 키오스크라면 자동 선택하게 해야 합니다.

```js
// main.js — 창 만든 뒤
win.webContents.session.on('select-serial-port', (event, portList, webContents, callback) => {
  event.preventDefault();
  // 키오스크에서는 사용자에게 묻지 않고 첫 포트를 자동 선택한다.
  callback(portList[0]?.portId ?? '');
});
win.webContents.session.setPermissionCheckHandler((wc, permission) => permission === 'serial');
win.webContents.session.setDevicePermissionHandler(() => true);
```

```js
// renderer
const port = await navigator.serial.requestPort();
await port.open({ baudRate: 38400, dataBits: 8, parity: 'none', stopBits: 1 });
const writer = port.writable.getWriter();
await writer.write(new Uint8Array([0x1b, 0x70, 0x00, 0x19, 0xfa]));  // 2번 핀 킥
writer.releaseLock();
```

> 트레이드오프: 간편하지만 하드웨어 접근이 렌더러에 생깁니다.
> 업무용이라면 방법 A 로 메인 프로세스에 가두는 편이 안전합니다.

---

## 4. **가장 중요한 부분** — 실제로 열렸는지 판정하기

`ESC p` 를 보냈다고 열린 게 아닙니다. 확인하려면 `DLE EOT 1` 의 **bit2(핀3)** 를 봐야 하는데,
여기 함정이 있습니다.

> **ESC/POS 규격은 핀3 의 전압 레벨만 정의하고, 어느 쪽이 '열림'인지는 정하지 않습니다.**
> 금전함 스위치가 NO 냐 NC 냐에 따라 반대가 됩니다.

그래서 **레벨을 고정 해석하면 안 되고, 킥 전후 변화를 봐야 합니다.**

| 킥 전 → 킥 후 | 판정 |
|---|---|
| HIGH → LOW | 열림 확인 |
| LOW → HIGH | 열림 확인 (**센서 극성이 반대인 금전함**) |
| 변화 없음 | **확인 불가** — 감지 스위치가 없거나, 서랍이 안 열렸거나 |

**"변화 없음"을 실패로 처리하면 안 됩니다.** 열림 감지 스위치가 아예 없는 금전함이 흔하고,
있어도 6가닥(RJ-12) 케이블이 아니면 신호 GND(6번 핀)가 빠져 감지되지 않습니다.
서랍은 멀쩡히 열립니다. 실패로 몰면 정상 장비를 고장으로 오해하게 됩니다.

```js
// drawer.js
import { drawerKick, drawerKickRealtime, statusQuery, pin3High, DrawerPin } from './escpos.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * 금전함을 열고 핀3 변화로 실제 개방 여부를 판정한다.
 *
 * @returns {Promise<{status:'opened'|'unverified'|'sent', detail:string, inverted?:boolean}>}
 *   opened     — 열린 것을 확인함
 *   unverified — 명령은 나갔지만 확인 불가 (경고로 표시할 것, 실패 아님)
 *   sent       — 단방향 연결이라 애초에 확인이 불가능
 */
export async function kickDrawer(transport, {
  pin = DrawerPin.PIN_2,
  realtime = false,
  timeoutMs = 1500,
  pollMs = 100,
} = {}) {
  // 1) 킥 전 핀3 레벨을 기준으로 잡아 둔다.
  let before = null;
  if (transport.supportsRead) {
    try {
      before = pin3High(await transport.query(statusQuery(1)));
    } catch {
      // 기준을 못 잡아도 킥은 해 본다. 판정만 불가해진다.
    }
  }

  // 2) 킥.
  await transport.write(realtime ? drawerKickRealtime(pin) : drawerKick(pin));

  if (!transport.supportsRead) {
    return { status: 'sent', detail: '킥 명령 전송 완료 (단방향이라 열림 확인 불가)' };
  }
  if (before === null) {
    return { status: 'unverified', detail: '킥 명령 전송 완료 (열림 확인 불가)' };
  }

  // 3) 솔레노이드가 튀고 서랍이 밀려 나와 스위치를 건드릴 때까지 잠깐 폴링한다.
  //    한 번만 읽으면 너무 일러서 놓친다.
  const deadline = Date.now() + timeoutMs;
  let after = before;
  while (true) {
    await sleep(pollMs);
    try {
      after = pin3High(await transport.query(statusQuery(1)));
    } catch {
      return { status: 'unverified', detail: '킥 후 상태를 읽지 못했습니다' };
    }
    if (after !== before) break;
    if (Date.now() >= deadline) break;
  }

  if (after !== before) {
    const inverted = before === false;   // LOW 에서 시작했다면 극성이 반대다
    return {
      status: 'opened',
      inverted,
      detail: inverted ? '금전함 열림 확인 (센서 극성이 일반과 반대)' : '금전함 열림 확인',
    };
  }

  return {
    status: 'unverified',
    detail: '킥 명령 전송 완료 · 열림 감지 안 됨 (서랍이 열렸는지 눈으로 확인하세요)',
  };
}
```

### 열리지 않을 때 체크리스트 (UI 에 그대로 노출하세요)

1. **반대쪽 핀으로 재시도** — 2번 핀 ↔ 5번 핀. 기종마다 배선이 다릅니다.
2. **솔레노이드 전압 확인** — 범일금고 EC-410 은 **12V 모델과 24V 모델이 따로** 있습니다.
   24V 금전함을 12V 포트에 물리면 **"딸깍" 소리만 나고 열리지 않습니다.** 가장 흔한 원인입니다.
3. **RJ-11 / RJ-12 체결** — 전화선 포트처럼 생겨서 헐겁게 걸쳐진 경우가 많습니다.
4. **금전함 측면 수동 키** 가 잠금(LOCK) 위치인지 확인.

---

## 5. Electron 배선

하드웨어 접근은 메인 프로세스에만 두고, 렌더러에는 `contextBridge` 로 좁은 API 만 엽니다.

```js
// main.js
import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'node:path';
import { SerialPort } from 'serialport';
import { SerialTransport } from './transport-serial.js';
import { WinSpoolerTransport } from './transport-winspool.js';
import { kickDrawer } from './drawer.js';
import { DrawerPin } from './escpos.js';

let transport = null;

// 오류는 삼키지 말고 사람이 읽을 수 있는 문장으로 바꿔 렌더러에 넘긴다.
const handle = (channel, fn) =>
  ipcMain.handle(channel, async (_event, ...args) => {
    try {
      return { ok: true, data: await fn(...args) };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  });

handle('pos:listPorts', async () =>
  (await SerialPort.list()).map((p) => ({ path: p.path, label: p.friendlyName ?? p.manufacturer ?? p.path })),
);

handle('pos:connect', async (opts) => {
  if (transport) await transport.close();
  transport = opts.mode === 'usb'
    ? new WinSpoolerTransport(opts.printerName)
    : new SerialTransport({ path: opts.path, baudRate: opts.baudRate });
  await transport.open();
  return { displayName: transport.displayName, supportsRead: transport.supportsRead };
});

handle('pos:disconnect', async () => {
  if (transport) await transport.close();
  transport = null;
});

handle('pos:kickDrawer', async ({ pin = 2, realtime = false } = {}) => {
  if (!transport) throw new Error('아직 연결되지 않았습니다.');
  return kickDrawer(transport, {
    pin: pin === 5 ? DrawerPin.PIN_5 : DrawerPin.PIN_2,
    realtime,
  });
});

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1024,
    height: 768,
    webPreferences: {
      preload: path.join(import.meta.dirname, 'preload.js'),
      contextIsolation: true,      // 렌더러에 Node 를 열어 주지 않는다
      nodeIntegration: false,
    },
  });
  win.loadFile('index.html');
});
```

```js
// preload.js
const { contextBridge, ipcRenderer } = require('electron');

// 포트 객체 자체를 넘기지 않고, 필요한 동작만 좁게 연다.
contextBridge.exposeInMainWorld('pos', {
  listPorts:  ()      => ipcRenderer.invoke('pos:listPorts'),
  connect:    (opts)  => ipcRenderer.invoke('pos:connect', opts),
  disconnect: ()      => ipcRenderer.invoke('pos:disconnect'),
  kickDrawer: (opts)  => ipcRenderer.invoke('pos:kickDrawer', opts),
});
```

```js
// renderer
const res = await window.pos.kickDrawer({ pin: 2 });

if (!res.ok) {
  showError(res.error);                       // 빨강
} else if (res.data.status === 'opened') {
  showSuccess(res.data.detail);               // 초록
} else {
  showWarning(res.data.detail);               // 노랑 — 실패가 아니다
  showChecklistLink();
}
```

**결과를 성공/실패 두 가지로만 표시하지 마세요.** `unverified` 는 세 번째 상태(노랑)로 두어야
센서 없는 정상 금전함을 고장으로 오해하지 않습니다.

---

## 6. 패키징 주의사항

| 항목 | 내용 |
|---|---|
| 네이티브 모듈 | `serialport` 는 Electron ABI 로 재빌드 필요 → `npx electron-builder install-app-deps` |
| asar | 네이티브 `.node` 는 `asarUnpack` 에 넣어야 로드됩니다 → `"asarUnpack": ["**/*.node"]` |
| 관리자 권한 | COM 포트·스풀러 모두 일반 사용자 권한으로 됩니다. `requestedExecutionLevel: asInvoker` 유지 |
| PowerShell | 방법 B 는 `-ExecutionPolicy Bypass` 로 호출하므로 정책 변경이 필요 없습니다 |
| 백신 오탐 | exe 압축(UPX)은 끄는 편이 안전합니다 |

`package.json` 예시:

```json
{
  "build": {
    "asarUnpack": ["**/*.node"],
    "win": {
      "target": "nsis",
      "requestedExecutionLevel": "asInvoker"
    }
  }
}
```

---

## 7. 하드웨어 없이 테스트하기

`pos_tester` 와 같은 방식으로 가짜 프린터를 만들면 장비 없이 전체 흐름을 돌려 볼 수 있습니다.
특히 **센서 없는 금전함**과 **극성 반대 금전함**을 흉내 낼 수 있어야 위 판정 로직을 검증할 수 있습니다.

```js
// transport-mock.js
export class MockTransport {
  constructor({ sensorWired = true, sensorInverted = false, opens = true } = {}) {
    this.supportsRead = true;
    this.displayName = '가상 프린터 (Mock)';
    this.state = { open: false, sensorWired, sensorInverted, opens };
    this.received = [];
  }

  async open() {}
  async close() {}

  async write(buffer) {
    this.received.push(Buffer.from(buffer));
    // ESC p (1B 70) 또는 DLE DC4 (10 14) 면 서랍을 연다.
    const isKick =
      (buffer[0] === 0x1b && buffer[1] === 0x70) ||
      (buffer[0] === 0x10 && buffer[1] === 0x14);
    if (isKick && this.state.opens) this.state.open = true;
  }

  async query() {
    let byte = 0b0001_0010;                    // bit1·bit4 고정
    if (this.#pin3High()) byte |= 0x04;
    return byte;
  }

  /** 센서선이 없으면 서랍 상태와 무관하게 계속 HIGH 다. */
  #pin3High() {
    if (!this.state.sensorWired) return true;
    return this.state.sensorInverted ? this.state.open : !this.state.open;
  }
}
```

검증해야 할 네 가지:

```js
await expect(kick(new MockTransport())).resolves.toMatchObject({ status: 'opened' });
await expect(kick(new MockTransport({ sensorInverted: true }))).resolves.toMatchObject({ status: 'opened', inverted: true });
await expect(kick(new MockTransport({ sensorWired: false }))).resolves.toMatchObject({ status: 'unverified' });
await expect(kick(new MockTransport({ opens: false }))).resolves.toMatchObject({ status: 'unverified' });
```

마지막 두 가지가 **같은 결과**인 점에 주의하세요.
핀3 만으로는 "센서가 없다"와 "서랍이 안 열렸다"를 원리적으로 구분할 수 없습니다.
그래서 사용자에게 **"서랍이 실제로 열렸는지 눈으로 확인하세요"** 라고 먼저 물어야 합니다.

---

## 8. 참고 — 통신 속도 자동 탐색

포트는 맞는데 baud 를 모를 때 씁니다. 각 속도로 `DLE EOT 1` 을 보내
**고정 비트(bit0=0, bit1=1, bit4=1, bit7=0)** 를 만족하는 응답이 오는 속도를 찾습니다.
속도가 어긋나면 깨진 바이트가 오는데, 이 검사로 걸러집니다.

```js
const BAUD_RATES = [9600, 19200, 38400, 57600, 115200];

export async function scanBaudRates(portPath, onProgress) {
  for (const baudRate of BAUD_RATES) {
    onProgress?.(baudRate);
    const transport = new SerialTransport({ path: portPath, baudRate });
    try {
      await transport.open();
      const byte = await transport.query(statusQuery(1), 600);
      if (isValidStatusByte(byte)) return baudRate;
    } catch {
      // 응답 없음 — 다음 속도로
    } finally {
      await transport.close();
    }
  }
  return null;
}
```

UI 를 막지 않도록 메인 프로세스에서 돌리고 진행 상황만 IPC 로 흘려보내세요.
