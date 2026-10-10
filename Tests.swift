import Cocoa
import ImageIO

func check(_ condition: @autoclosure () throws -> Bool) throws {
    let ok = try condition()
    if !ok { throw fail("offline_test_assertion_failed") }
}

// Offline tests use fabricated content only. No live app, contacts or network.
func fixture(draft:Bool = false, placeholder:Bool = false) -> CGImage {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:1000,pixelsHigh:800,
        bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
    NSColor.white.setFill(); NSRect(x:0,y:0,width:1000,height:800).fill()
    NSColor(calibratedRed:0.68,green:0.94,blue:0.64,alpha:1).setFill()
    NSRect(x:600,y:270,width:380,height:55).fill()
    let attrs:[NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:20),.foregroundColor:NSColor.black]
    ("Demo Contact" as NSString).draw(at:NSPoint(x:316,y:750),withAttributes:attrs)
    ("Test message 123" as NSString).draw(at:NSPoint(x:620,y:285),withAttributes:attrs)
    if placeholder { ("Hold mouse to input by voice" as NSString).draw(at:NSPoint(x:320,y:185),withAttributes:attrs) }
    if draft { ("Draft stays here" as NSString).draw(at:NSPoint(x:320,y:185),withAttributes:attrs) }
    NSGraphicsContext.restoreGraphicsState()
    return bitmap.cgImage!
}
@main struct OfflineTests {
    static func main() throws {
        _ = NSApplication.shared
        // Optional local regression fixture; no file contents are printed.
        if CommandLine.arguments.count == 4 {
            let url = URL(fileURLWithPath:CommandLine.arguments[1])
            let source = CGImageSourceCreateWithURL(url as CFURL,nil)!
            let image = CGImageSourceCreateImageAtIndex(source,0,nil)!
            let left = try chatLeft(image,chat:CommandLine.arguments[2])
            print("fixture left",left,"empty",try composerEmpty(image,left:left,top:0.695),
                  "outgoing",try outgoingContains(image,left:left,top:0.695,text:CommandLine.arguments[3]))
            return
        }
        let image = fixture()
        let left = try chatLeft(image,chat:"Demo Contact")
        try check(abs(left-300) < 8)
        try check(try composerEmpty(image,left:left,top:0.70))
        try check(try outgoingContains(image,left:left,top:0.70,text:"Test message 123"))
        try check(try !outgoingContains(image,left:left,top:0.70,text:"Not there"))
        try check(try composerEmpty(fixture(placeholder:true),left:left,top:0.70))
        let draft = fixture(draft:true)
        try check(try !composerEmpty(draft,left:left,top:0.70))
        try check(normalized(try composerText(draft,left:left,top:0.70)) == "Draftstayshere")
        do { _ = try chatLeft(image,chat:"Wrong Contact"); preconditionFailure("wrong recipient accepted") }
        catch { try check(error.localizedDescription == "chat_title_not_verified") }
        testSendUtilities()
        try validateArguments(["send","--chat","Demo","--text","test","--id","one","--composer-top","0.7","--dry-run"])
        for args in [["send","--dryrun"],["read","--chat"],["read","--chat","One","--chat","Two"]] {
            do { try validateArguments(args); preconditionFailure("unsafe arguments accepted") } catch {}
        }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("wechat-test-"+UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:dir) }
        var journal:Journal? = try Journal(directory:dir.path,id:"example-id",signature:digest("payload"))
        try check(try journal?.existing() == nil)
        try journal?.save("dispatching")
        try check(try journal?.existing() == "dispatching")
        journal = nil
        journal = try Journal(directory:dir.path,id:"example-id",signature:digest("payload"))
        try check(try journal?.existing() == "dispatching")
        try journal?.save("sent_ui_verified")
        try check(try journal?.existing() == "sent_ui_verified")
        journal = nil
        journal = try Journal(directory:dir.path,id:"example-id",signature:digest("different"))
        do { _ = try journal?.existing(); preconditionFailure("id collision accepted") }
        catch { try check(error.localizedDescription == "id_reused_with_different_payload") }
        journal = nil
        print("PASS: title, blank/draft composer, green outgoing text, ID journal, text validation")
    }
}
