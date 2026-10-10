import Cocoa
import ScreenCaptureKit
import Vision
import CoreMedia
import CoreImage
import ImageIO
import UniformTypeIdentifiers

// MIT licensed. Local ScreenCaptureKit/Vision reader; see Send.swift for explicit sends.
func emit(_ event: [String: Any]) {
    var value = event
    value["at"] = ISO8601DateFormatter().string(from: Date())
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
       let string = String(data: data, encoding: .utf8) { print(string); fflush(stdout) }
}
func option(_ name: String, _ fallback: String) -> String {
    guard let i = CommandLine.arguments.firstIndex(of: name), i + 1 < CommandLine.arguments.count else { return fallback }
    return CommandLine.arguments[i + 1]
}
struct Line {
    let text: String
    let box: CGRect
    let confidence: Float
    var json: [String: Any] { ["text": text, "x": box.minX, "y": 1-box.maxY,
        "width": box.width, "height": box.height, "confidence": confidence] }
}
func recognize(_ image: CGImage) throws -> [Line] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: image).perform([request])
    return (request.results ?? []).compactMap {
        guard let text = $0.topCandidates(1).first else { return nil }
        return Line(text: text.string, box: $0.boundingBox, confidence: text.confidence)
    }.sorted { $0.box.midY > $1.box.midY }
}
// A small grayscale representation avoids re-running OCR on an unchanged panel.
func pixels(_ image: CGImage) -> [UInt8] {
    var data = [UInt8](repeating: 0, count: 200 * 160)
    data.withUnsafeMutableBytes { p in
        let context = CGContext(data: p.baseAddress, width: 200, height: 160,
            bitsPerComponent: 8, bytesPerRow: 200, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0)!
        context.draw(image, in: CGRect(x: 0, y: 0, width: 200, height: 160))
    }
    return data
}
func difference(_ a: [UInt8], _ b: [UInt8]) -> Double {
    guard a.count == b.count, !a.isEmpty else { return .infinity }
    return zip(a,b).reduce(0.0) { $0 + Double(abs(Int($1.0)-Int($1.1))) } / Double(a.count)
}
func isBlank(_ data: [UInt8]) -> Bool {
    guard let lo = data.min(), let hi = data.max() else { return true }
    return Int(hi)-Int(lo) < 8
}
// Only reports an appended OCR sequence if previous visible context overlaps.
// Reflow, OCR corrections, scrolling and lack of overlap produce a reset instead.
func appendStart(old: [String], new: [String]) -> Int? {
    guard !old.isEmpty, !new.isEmpty else { return nil }
    for count in stride(from: min(old.count, new.count), through: 1, by: -1) {
        if Array(old.suffix(count)) == Array(new.prefix(count)) { return count }
    }
    return nil
}

final class CaptureSession: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private let context = CIContext()
    private var image: CGImage?
    private var failure: Error?
    private var sequence = 0
    private var stream: SCStream?
    var key = ""
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sample.isValid, let pixel = sample.imageBuffer else { return }
        let input = CIImage(cvPixelBuffer: pixel)
        guard let frame = context.createCGImage(input, from: input.extent) else { return }
        lock.lock(); image = frame; sequence += 1; lock.unlock()
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        lock.lock(); failure = error; lock.unlock()
    }
    func serial() -> Int { lock.lock(); defer { lock.unlock() }; return sequence }
    func latest() throws -> CGImage? {
        lock.lock(); defer { lock.unlock() }
        if let failure { throw failure }
        return image
    }
    func start(window: SCWindow, display: SCDisplay, interval: Double) async throws {
        guard let app = window.owningApplication else { throw NSError(domain:"capture",code:1) }
        let config = SCStreamConfiguration()
        config.width = Int(window.frame.width); config.height = Int(window.frame.height)
        config.showsCursor = false
        config.minimumFrameInterval = CMTime(seconds: interval, preferredTimescale: 600)
        config.queueDepth = 3
        config.sourceRect = CGRect(x:window.frame.minX-display.frame.minX,
            y:window.frame.minY-display.frame.minY, width:window.frame.width, height:window.frame.height)
        // Reproducible macOS workaround: app-filter stream -> window-filter update.
        // Direct single-window streams and one-shot screenshots omit this WeChat window.
        let initial = SCContentFilter(display:display, including:[app], exceptingWindows:[])
        let active = SCStream(filter:initial, configuration:config, delegate:self)
        stream = active
        try active.addStreamOutput(self, type:.screen, sampleHandlerQueue:DispatchQueue(label:"wechat.frames"))
        try await active.startCapture()
        try await Task.sleep(for:.milliseconds(250))
        try await active.updateContentFilter(SCContentFilter(display:display, including:[window]))
        try await Task.sleep(for:.milliseconds(550))
    }
    func stop() async { if let stream { try? await stream.stopCapture() }; stream = nil }
}

#if !LIBRARY
@main struct Monitor {
    static func main() async {
        _ = NSApplication.shared
        let command = CommandLine.arguments.dropFirst().first ?? "help"
        if command == "help" || CommandLine.arguments.contains("--help") { printUsage(); return }
        do { try validateArguments(Array(CommandLine.arguments.dropFirst())) }
        catch { emit(["type":"error", "reason":error.localizedDescription]); exit(2) }
        if command == "doctor" { doctor(); return }
        if command == "send" {
            do { try await sendMessage() } catch {
                emit(["type":"error", "reason":error.localizedDescription]); exit(2)
            }
            return
        }
        guard ["read", "watch", "self-test"].contains(command) else { printUsage(); exit(2) }
        if command == "self-test" {
            testSendUtilities()
            precondition(isBlank([0,0,0]) && !isBlank([0,255]))
            precondition(difference([0,100], [0,102]) == 1)
            precondition(appendStart(old:["a","b"],new:["b","c"]) == 1)
            precondition(appendStart(old:["a","b"],new:["a","b","b"]) == 2)
            precondition(appendStart(old:["a"],new:["z"]) == nil)
            emit(["type":"self_test", "passed":true]); return
        }
        let chat = option("--chat", "")
        guard !chat.isEmpty else { emit(["type":"error", "reason":"--chat is required"]); exit(2) }
        guard let seconds = Double(option("--seconds", "30")), seconds.isFinite, seconds >= 1,
              let interval = Double(option("--interval", "0.5")), interval.isFinite, interval >= 0.25, interval <= 10 else {
            emit(["type":"error", "reason":"invalid --seconds or --interval"]); exit(2)
        }
        guard let composerTop = Double(option("--composer-top", "0.70")), composerTop.isFinite,
              composerTop >= 0.45, composerTop <= 0.88 else {
            emit(["type":"error", "reason":"invalid_composer_top"]); exit(2)
        }
        var panelX: Double?
        let once = command == "read"
        let snapshot = option("--snapshot", "")
        guard CGPreflightScreenCaptureAccess() else {
            emit(["type":"blocked", "reason":"screen_recording_permission_missing"]); exit(2)
        }
        var previousPixels: [UInt8] = []
        var previousLines: [String] = []
        var previousWindow: CGWindowID?
        var session: CaptureSession?
        var lastStatus = ""
        var frames = 0, ocrRuns = 0, skipped = 0
        var captureTimes: [Double] = [], ocrTimes: [Double] = []
        let started = Date()
        emit(["type":"started", "chat":chat, "mode":"read_only", "interval_seconds":interval])
        while Date().timeIntervalSince(started) < seconds {
            let tick = Date()
            do {
                guard !screenLocked() else { throw fail("screen_locked") }
                let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
                let candidates = content.windows.filter {
                    $0.owningApplication?.bundleIdentifier == "com.tencent.xinWeChat" &&
                    ["Weixin", "WeChat", "微信"].contains($0.title ?? "") &&
                    $0.frame.width > 600 && $0.frame.height > 450
                }
                guard let window = candidates.max(by: { $0.frame.width < $1.frame.width }) else {
                    throw NSError(domain:"monitor", code:1, userInfo:[NSLocalizedDescriptionKey:"main_window_unavailable"])
                }
                if previousWindow != window.windowID {
                    previousPixels = []; previousLines = []; previousWindow = window.windowID
                }
                guard let display = content.displays.first(where: { $0.frame.contains(window.frame) }) else {
                    throw NSError(domain:"monitor",code:3,userInfo:[NSLocalizedDescriptionKey:"window_must_fit_one_display"])
                }
                let key = "\(window.windowID):\(window.frame):\(display.displayID)"
                let beforeCapture = Date()
                if session?.key != key {
                    await session?.stop()
                    let fresh = CaptureSession(); session = fresh
                    try await fresh.start(window:window, display:display, interval:interval)
                    fresh.key = key; previousPixels = []; previousLines = []; panelX = nil
                    emit(["type":"capture_ready", "backend":"SCStream_app_to_window", "window_id":window.windowID])
                }
                var newest = try session?.latest()
                if newest == nil {
                    for _ in 0..<30 {
                        try await Task.sleep(for:.milliseconds(50))
                        newest = try session?.latest()
                        if newest != nil { break }
                    }
                }
                guard let image = newest else {
                    throw NSError(domain:"monitor",code:4,userInfo:[NSLocalizedDescriptionKey:"no_frame_after_filter_refresh"])
                }
                let captureMS = Date().timeIntervalSince(beforeCapture)*1000
                captureTimes.append(captureMS); frames += 1
                if frames == 1 && !snapshot.isEmpty {
                    if let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath:snapshot) as CFURL,
                        UTType.png.identifier as CFString, 1, nil) {
                        CGImageDestinationAddImage(dest, image, nil); CGImageDestinationFinalize(dest)
                    }
                }
                if panelX == nil { panelX = try chatLeft(image, chat:chat) / Double(image.width) }
                let x = panelX!
                let rect = CGRect(x:Double(image.width)*x, y:0,
                    width:Double(image.width)*(1-x), height:Double(image.height)*composerTop).integral
                guard let panel = image.cropping(to:rect) else { throw NSError(domain:"monitor",code:2) }
                let small = pixels(panel)
                if isBlank(small) {
                    if lastStatus != "blank" { emit(["type":"blocked", "reason":"blank_capture", "window_id":window.windowID]) }
                    lastStatus = "blank"; previousPixels = []; previousLines = []
                } else if difference(previousPixels, small) < 0.15 {
                    skipped += 1
                } else {
                    let beforeOCR = Date()
                    let lines = try recognize(panel)
                    let ocrMS = Date().timeIntervalSince(beforeOCR)*1000
                    ocrTimes.append(ocrMS); ocrRuns += 1
                    let headers = lines.filter { 1-$0.box.maxY < 0.12 }
                    guard headers.contains(where: { normalized($0.text) == normalized(chat) && $0.confidence >= 0.5 }) else {
                        if lastStatus != "unverified" { emit(["type":"blocked", "reason":"chat_title_not_verified", "expected":chat]) }
                        lastStatus = "unverified"; previousLines = []; previousPixels = small
                        if once { break }
                        try await Task.sleep(nanoseconds: UInt64(interval*1_000_000_000)); continue
                    }
                    let body = lines.filter { 1-$0.box.maxY >= 0.12 }
                    let texts = body.map(\.text)
                    let kind: String
                    let offset: Int
                    if previousLines.isEmpty { kind = "baseline"; offset = 0 }
                    else if texts == previousLines { kind = "unchanged_text"; offset = texts.count }
                    else if let start = appendStart(old: previousLines, new: texts) { kind = "candidate_added_lines"; offset = start }
                    else { kind = "context_reset"; offset = 0 }
                    if kind != "unchanged_text" {
                        emit(["type":kind, "chat":chat, "sender":"unverified", "safe_to_autoreply":false,
                            "lines":Array(body.dropFirst(offset)).map(\.json), "capture_ms":captureMS, "ocr_ms":ocrMS])
                    }
                    lastStatus = "readable"; previousLines = texts; previousPixels = small
                }
            } catch {
                let reason = error.localizedDescription
                if lastStatus != reason { emit(["type":"blocked", "reason":reason]) }
                lastStatus = reason; previousPixels = []; previousLines = []
                await session?.stop(); session = nil
            }
            if once { break }
            let remaining = interval-Date().timeIntervalSince(tick)
            if remaining > 0 { try? await Task.sleep(nanoseconds: UInt64(remaining*1_000_000_000)) }
        }
        await session?.stop()
        func average(_ values:[Double]) -> Double { values.isEmpty ? 0 : values.reduce(0,+)/Double(values.count) }
        emit(["type":"stopped", "frames":frames, "ocr_runs":ocrRuns, "unchanged_skipped":skipped,
            "frame_fetch_mean_ms":average(captureTimes), "ocr_mean_ms":average(ocrTimes), "last_status":lastStatus,
            "elapsed_seconds":Date().timeIntervalSince(started)])
        if lastStatus != "readable" { exit(2) }
    }
}

#endif
