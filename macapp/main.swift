// 기획 위키 — macOS 앱 껍데기
// 로컬 Python 서버(server.py)를 띄우고, 그 화면을 네이티브 창(WKWebView)으로 보여준다.
// 앱을 종료하면 앱이 띄운 서버도 같이 꺼진다.

import Cocoa
import WebKit

struct AppConfig {
    let bundled: Bool     // 배포판: 앱 안에 든 wiki-server 실행 파일을 쓴다
    let root: String      // (개발판) server.py가 있는 폴더
    let python: String    // python3 절대 경로
    let path: String      // claude / codex CLI를 찾기 위한 PATH
    let port: Int

    static func load() -> AppConfig {
        let url = Bundle.main.url(forResource: "app-config", withExtension: "json")!
        let obj = (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:]
        return AppConfig(
            bundled: obj["bundled"] as? Bool ?? false,
            root: obj["root"] as? String ?? "",
            python: obj["python"] as? String ?? "/usr/bin/python3",
            path: obj["path"] as? String ?? "/usr/bin:/bin",
            port: obj["port"] as? Int ?? 4173
        )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    let config = AppConfig.load()
    var baseURL: URL { URL(string: "http://127.0.0.1:\(config.port)/")! }
    var logPath: String {
        if config.bundled {
            return (NSHomeDirectory() as NSString).appendingPathComponent("Library/Logs/기획위키/server.log")
        }
        return (config.root as NSString).appendingPathComponent("data/server.log")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        showMessage("기획 위키를 여는 중…", sub: "")
        startServerIfNeeded()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        if let p = server, p.isRunning { p.terminate() }
    }

    // MARK: - window

    func buildWindow() {
        let cfg = WKWebViewConfiguration()
        // window.print() → 네이티브 인쇄(PDF 저장) 창
        let script = WKUserScript(source: "window.print = () => window.webkit.messageHandlers.native.postMessage('print');",
                                  injectionTime: .atDocumentStart, forMainFrameOnly: true)
        cfg.userContentController.addUserScript(script)
        cfg.userContentController.add(self, name: "native")

        webView = WKWebView(frame: .zero, configuration: cfg)
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.allowsMagnification = true
        webView.allowsBackForwardNavigationGestures = true

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "기획 위키"
        window.minSize = NSSize(width: 720, height: 520)
        window.contentView = webView
        window.setFrameAutosaveName("MainWindow")
        if !window.setFrameUsingName("MainWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showMessage(_ title: String, sub: String) {
        let html = """
        <html><body style="margin:0;height:100vh;display:grid;place-items:center;font:15px -apple-system;color:#6b6862;background:#f6f5f2">
        <div style="text-align:center;max-width:560px;padding:24px"><div style="font-size:42px;color:#5b47e0">◆</div>
        <div style="font-weight:700;color:#1d1c1a;margin:10px 0 6px">\(title)</div><div style="white-space:pre-wrap">\(sub)</div></div>
        <style>@media (prefers-color-scheme: dark){body{background:#161615!important;color:#9d9a93!important}div div:nth-child(2){color:#ecebe7!important}}</style>
        </body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: - server

    func ping(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: baseURL.appendingPathComponent("api/config"))
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func startServerIfNeeded() {
        ping { [self] alive in
            if alive { return openWiki() }   // 이미 켜진 서버(start.command 등)가 있으면 그걸 쓴다
            launchServer()
            waitForServer(tries: 120)
        }
    }

    func launchServer() {
        let fm = FileManager.default
        let p = Process()
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        if config.bundled {
            guard let exe = Bundle.main.url(forAuxiliaryExecutable: "wiki-server") else {
                return showMessage("앱 파일이 손상됐어요", sub: "기획위키를 다시 내려받아 설치해 주세요.")
            }
            p.executableURL = exe
            p.arguments = ["--serve"]
            p.currentDirectoryURL = URL(fileURLWithPath: NSHomeDirectory())
        } else {
            let serverPy = (config.root as NSString).appendingPathComponent("server.py")
            guard fm.fileExists(atPath: serverPy) else {
                return showMessage("server.py를 찾을 수 없어요", sub: "\(config.root)\n\n기획위키 폴더를 옮겼다면 폴더 안의 build_app.command를 다시 실행해 주세요.")
            }
            p.executableURL = URL(fileURLWithPath: config.python)
            p.arguments = [serverPy]
            p.currentDirectoryURL = URL(fileURLWithPath: config.root)
            env["PATH"] = config.path
        }
        p.environment = env
        try? fm.createDirectory(atPath: (logPath as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
        fm.createFile(atPath: logPath, contents: nil)
        if let log = FileHandle(forWritingAtPath: logPath) {
            p.standardOutput = log
            p.standardError = log
        }
        do {
            try p.run()
            server = p
        } catch {
            showMessage("서버를 시작하지 못했어요", sub: error.localizedDescription)
        }
    }

    func waitForServer(tries: Int) {
        ping { [self] alive in
            if alive { return openWiki() }
            if let p = server, !p.isRunning {
                let log = (try? String(contentsOfFile: logPath, encoding: .utf8)) ?? ""
                return showMessage("서버가 바로 종료됐어요", sub: String(log.suffix(600)))
            }
            if tries <= 0 { return showMessage("서버 응답이 없어요", sub: "로그 파일을 확인해 주세요.\n\(logPath)") }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer(tries: tries - 1) }
        }
    }

    func openWiki() {
        webView.load(URLRequest(url: baseURL))
    }

    // MARK: - menu

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu()
        app.addItem(withTitle: "기획 위키 정보", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "기획 위키 가리기", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(.separator())
        app.addItem(withTitle: "기획 위키 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app

        let fileItem = NSMenuItem(); main.addItem(fileItem)
        let file = NSMenu(title: "파일")
        file.addItem(withTitle: "새 문서", action: #selector(newDoc), keyEquivalent: "n")
        file.addItem(withTitle: "프로젝트 홈", action: #selector(goHome), keyEquivalent: "H").keyEquivalentModifierMask = [.command, .shift]
        file.addItem(withTitle: "프로젝트 목록", action: #selector(goProjects), keyEquivalent: "O").keyEquivalentModifierMask = [.command, .shift]
        file.addItem(.separator())
        file.addItem(withTitle: "인쇄 / PDF로 저장…", action: #selector(printPage), keyEquivalent: "p")
        file.addItem(.separator())
        file.addItem(withTitle: "Finder에서 폴더 열기", action: #selector(revealFolder), keyEquivalent: "")
        file.addItem(withTitle: "창 닫기", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = file

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "편집")
        edit.addItem(withTitle: "실행 취소", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "실행 복귀", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "잘라내기", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "복사", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "붙여넣기", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "모두 선택", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.addItem(.separator())
        edit.addItem(withTitle: "찾기", action: #selector(focusSearch), keyEquivalent: "f")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "보기")
        view.addItem(withTitle: "새로고침", action: #selector(reload), keyEquivalent: "r")
        view.addItem(withTitle: "뒤로", action: #selector(goBack), keyEquivalent: "[")
        view.addItem(withTitle: "앞으로", action: #selector(goForward), keyEquivalent: "]")
        view.addItem(.separator())
        view.addItem(withTitle: "확대", action: #selector(zoomIn), keyEquivalent: "+")
        view.addItem(withTitle: "축소", action: #selector(zoomOut), keyEquivalent: "-")
        view.addItem(withTitle: "실제 크기", action: #selector(zoomReset), keyEquivalent: "0")
        view.addItem(.separator())
        view.addItem(withTitle: "전체 화면", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = view

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "윈도우")
        win.addItem(withTitle: "최소화", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "확대/축소", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        winItem.submenu = win
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }

    @objc func newDoc() { webView.evaluateJavaScript("window.wiki && window.wiki.newDoc()") }
    @objc func goHome() { webView.evaluateJavaScript("window.wiki && window.wiki.home()") }
    @objc func goProjects() { webView.evaluateJavaScript("window.wiki && window.wiki.projects()") }
    @objc func focusSearch() { webView.evaluateJavaScript("document.getElementById('search')?.focus()") }
    @objc func reload() { if webView.url?.host == nil { startServerIfNeeded() } else { webView.reload() } }
    @objc func goBack() { webView.goBack() }
    @objc func goForward() { webView.goForward() }
    @objc func zoomIn() { webView.pageZoom = min(webView.pageZoom + 0.1, 2.0) }
    @objc func zoomOut() { webView.pageZoom = max(webView.pageZoom - 0.1, 0.5) }
    @objc func zoomReset() { webView.pageZoom = 1.0 }
    @objc func revealFolder() {
        // 문서가 저장되는 폴더는 서버 설정(projectsDir)에 따라 달라지므로 서버에 물어본다
        URLSession.shared.dataTask(with: baseURL.appendingPathComponent("api/config")) { data, _, _ in
            let obj = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            guard let dir = obj?["projectsDir"] as? String else { return }
            DispatchQueue.main.async { NSWorkspace.shared.open(URL(fileURLWithPath: dir)) }
        }.resume()
    }

    @objc func printPage() {
        let info = NSPrintInfo.shared.copy() as! NSPrintInfo
        info.horizontalPagination = .fit
        info.verticalPagination = .automatic
        info.isHorizontallyCentered = false
        info.isVerticallyCentered = false
        info.topMargin = 20; info.bottomMargin = 20; info.leftMargin = 20; info.rightMargin = 20
        let op = webView.printOperation(with: info)
        op.view?.frame = webView.bounds
        op.showsPrintPanel = true
        op.showsProgressPanel = true
        op.runModal(for: window, delegate: nil, didRun: nil, contextInfo: nil)
    }

    // MARK: - JS bridge

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if (message.body as? String) == "print" { printPage() }
    }

    // MARK: - WKUIDelegate (alert / confirm / 파일 선택)

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "확인")
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message
        a.addButton(withTitle: "확인"); a.addButton(withTitle: "취소")
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.png, .jpeg, .gif, .webP]
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }

    // 외부 링크는 기본 브라우저로
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let host = url.host, host != "127.0.0.1", host != "localhost",
           action.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        if action.request.url?.isFileURL == true { return decisionHandler(.cancel) }  // 이미지를 잘못 끌어다 놓아도 화면이 바뀌지 않게
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
