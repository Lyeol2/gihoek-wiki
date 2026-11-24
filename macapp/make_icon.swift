// 앱 아이콘(1024px PNG) 그리기: swift make_icon.swift <출력.png>
import Cocoa

let size = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

let s = CGFloat(size)
// macOS 아이콘 그리드: 바깥 여백 약 10%
let body = NSRect(x: s * 0.1, y: s * 0.1, width: s * 0.8, height: s * 0.8)
let radius = s * 0.18

// 그림자
let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
shadow.shadowBlurRadius = s * 0.025
shadow.shadowOffset = NSSize(width: 0, height: -s * 0.012)
shadow.set()

let bg = NSBezierPath(roundedRect: body, xRadius: radius, yRadius: radius)
NSGradient(colors: [NSColor(red: 0.47, green: 0.36, blue: 1.0, alpha: 1),
                    NSColor(red: 0.27, green: 0.17, blue: 0.74, alpha: 1)])!.draw(in: bg, angle: -90)
NSShadow().set()

// 펼친 문서(책) 모양
let paperW = s * 0.46, paperH = s * 0.52
let paper = NSRect(x: (s - paperW) / 2, y: s * 0.2, width: paperW, height: paperH)
let page = NSBezierPath(roundedRect: paper, xRadius: s * 0.035, yRadius: s * 0.035)
NSColor.white.withAlphaComponent(0.96).setFill()
page.fill()

// 문서 위 줄
NSColor(red: 0.36, green: 0.28, blue: 0.88, alpha: 0.28).setFill()
let lineX = paper.minX + s * 0.06
for (i, w) in [0.30, 0.34, 0.22, 0.30].enumerated() {
    let r = NSRect(x: lineX, y: paper.minY + s * 0.07 + CGFloat(i) * s * 0.065, width: s * CGFloat(w), height: s * 0.028)
    NSBezierPath(roundedRect: r, xRadius: s * 0.014, yRadius: s * 0.014).fill()
}

// 상단 다이아몬드
let cx = s / 2, cy = paper.maxY - s * 0.13, d = s * 0.095
let dia = NSBezierPath()
dia.move(to: NSPoint(x: cx, y: cy + d))
dia.line(to: NSPoint(x: cx + d * 0.8, y: cy))
dia.line(to: NSPoint(x: cx, y: cy - d))
dia.line(to: NSPoint(x: cx - d * 0.8, y: cy))
dia.close()
NSGradient(colors: [NSColor(red: 1.0, green: 0.62, blue: 0.3, alpha: 1),
                    NSColor(red: 0.92, green: 0.36, blue: 0.24, alpha: 1)])!.draw(in: dia, angle: -90)

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("icon: \(out)")
