import Foundation
import AppKit
import PDFKit
import Vision
import ImageIO

let protocolVersion = 1
func send(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
}
func fail(_ message: String, page: Int? = nil) {
    var result: [String: Any] = ["event": "error", "message": message, "protocol_version": protocolVersion]
    if let page = page { result["page_no"] = page }
    send(result)
}
func rect(_ bounds: CGRect, pageBounds: CGRect) -> [Double] {
    [Double((bounds.minX-pageBounds.minX)/pageBounds.width), Double((pageBounds.maxY-bounds.maxY)/pageBounds.height), Double(bounds.width/pageBounds.width), Double(bounds.height/pageBounds.height)]
}
func rotatedRect(_ box: [Double], rotation: Int) -> [Double] {
    let x=box[0], y=box[1], w=box[2], h=box[3]
    switch ((rotation % 360)+360)%360 {
    case 90: return [1-y-h, x, h, w]
    case 180: return [1-x-w, 1-y-h, w, h]
    case 270: return [y, 1-x-w, h, w]
    default: return box
    }
}
func nativeBlocks(_ page: PDFPage) -> [[String: Any]] {
    let bounds = page.bounds(for: .cropBox)
    return (page.selection(for: bounds)?.selectionsByLine() ?? []).compactMap { selection in
        guard let text = selection.string?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return ["text": text, "bbox": rotatedRect(rect(selection.bounds(for: page).intersection(bounds), pageBounds: bounds), rotation: page.rotation), "source": "native"]
    }
}
func render(_ page: PDFPage, dpi: Double) throws -> CGImage {
    let bounds = page.bounds(for: .cropBox)
    guard bounds.width > 0, bounds.height > 0, dpi.isFinite, dpi > 0 else {
        throw NSError(domain: "PDFSplitter", code: 3, userInfo: [NSLocalizedDescriptionKey: "Invalid crop box or render DPI."])
    }
    var size = CGSize(width: bounds.width*dpi/72, height: bounds.height*dpi/72)
    if page.rotation % 180 != 0 { size = CGSize(width: size.height, height: size.width) }
    let pixels = size.width*size.height
    if pixels > 25_000_000 { let factor = sqrt(25_000_000/pixels); size.width *= factor; size.height *= factor }
    let image = page.thumbnail(of: size, for: .cropBox)
    guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { throw NSError(domain: "PDFSplitter", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot render PDF page."]) }
    return cg
}
func recognize(_ image: CGImage, languages: [String], pass: String, rotation: Int = 0) throws -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.revision = VNRecognizeTextRequestRevision3
    request.recognitionLevel = .accurate
    request.recognitionLanguages = languages
    request.usesLanguageCorrection = true
    let angle=((rotation % 360)+360)%360
    let orientation: CGImagePropertyOrientation = angle == 90 ? .left : (angle == 180 ? .down : (angle == 270 ? .right : .up))
    try VNImageRequestHandler(cgImage: image, orientation: orientation).perform([request])
    return (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        let text=candidate.string
        let regex=try? NSRegularExpression(pattern: "[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*")
        let segments=(regex?.matches(in: text, range: NSRange(text.startIndex..., in: text)) ?? []).compactMap { match -> [String: Any]? in
            guard let range=Range(match.range,in:text), let region=try? candidate.boundingBox(for: range) else { return nil }
            let b=region.boundingBox
            return ["text": String(text[range]), "start": text.distance(from: text.startIndex, to: range.lowerBound), "end": text.distance(from: text.startIndex,to:range.upperBound), "bbox": rotatedRect([b.minX,1-b.maxY,b.width,b.height],rotation:rotation)]
        }
        return ["text": candidate.string, "bbox": rotatedRect([box.minX, 1-box.maxY, box.width, box.height], rotation: rotation), "confidence": Double(candidate.confidence), "source": pass, "segments": segments, "candidates": observation.topCandidates(3).dropFirst().map { ["text": $0.string, "confidence": Double($0.confidence), "source": pass] as [String: Any] }]
    }
}
var documents: [String: PDFDocument] = [:]
func document(_ path: String) throws -> PDFDocument {
    if let cached = documents[path] { return cached }
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)), !doc.isLocked else { throw NSError(domain: "PDFSplitter", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot open PDF, or PDF requires a password."]) }
    documents = [path: doc]; return doc
}
while let line = readLine() {
    do {
        guard let data = line.data(using: .utf8), let request = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { fail("Invalid JSON request."); continue }
        let op = request["op"] as? String ?? ""
        if op == "capabilities" {
            let vision = VNRecognizeTextRequest(); vision.revision = VNRecognizeTextRequestRevision3; vision.recognitionLevel = .accurate
            send(["event": "capabilities", "protocol_version": protocolVersion, "revision": 3, "languages": try vision.supportedRecognitionLanguages(), "os": ProcessInfo.processInfo.operatingSystemVersionString, "dark": UserDefaults.standard.string(forKey: "AppleInterfaceStyle") == "Dark", "reduce_motion": NSWorkspace.shared.accessibilityDisplayShouldReduceMotion])
            continue
        }
        guard let path = request["pdf"] as? String else { fail("Missing PDF path."); continue }
        let doc = try document(path)
        if op == "preview" {
            let index = (request["page_no"] as? Int ?? 1)-1
            guard let page = doc.page(at: index), let output = request["output"] as? String else { fail("Invalid preview page or output."); continue }
            let image = try render(page, dpi: request["dpi"] as? Double ?? 100)
            guard let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
                fail("Cannot encode preview PNG."); continue
            }
            try png.write(to: URL(fileURLWithPath: output), options: .atomic)
            send(["event": "preview", "width": image.width, "height": image.height, "path": output]); continue
        }
        guard op == "extract" else { fail("Unknown operation."); continue }
        let numbers = request["pages"] as? [Int] ?? Array(1...max(doc.pageCount, 1))
        for number in numbers {
            send(["event": "progress", "page_no": number])
            autoreleasepool {
                do {
                    guard let page = doc.page(at: number-1) else { fail("Page out of range.", page: number); return }
                    let blocks = nativeBlocks(page)
                    let text = blocks.compactMap { $0["text"] as? String }.joined(separator: "\n")
                    let valid = text.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.count
                    let replacement = text.filter { $0 == "\u{FFFD}" }.count
                    let mode = request["mode"] as? String ?? "auto"
                    let blanks = request["blank_pages"] as? [Int] ?? []
                    let needsOCR = mode == "force" || (mode == "auto" && !blanks.contains(number) && (valid < 40 || Double(replacement)/Double(max(text.count,1)) > 0.1))
                    if !needsOCR {
                        send(["event": "page", "page_no": number, "blocks": blocks, "source": "native", "status": text.isEmpty ? "blank" : "ready"]); return
                    }
                    let image = try render(page, dpi: request["dpi"] as? Double ?? 300)
                    let profile = request["languages"] as? String ?? "mixed"
                    var recognized = try recognize(image, languages: ["en-US"], pass: "ocr_en", rotation: page.rotation)
                    if profile != "en" {
                        let languages = profile == "zh-Hant" ? ["zh-Hant", "zh-Hans", "en-US"] : ["zh-Hans", "zh-Hant", "en-US"]
                        recognized += try recognize(image, languages: languages, pass: "ocr_zh", rotation: page.rotation)
                    }
                    send(["event": "page", "page_no": number, "blocks": recognized, "native_blocks": blocks, "source": "ocr", "status": recognized.isEmpty ? "blank" : "ready"])
                } catch { fail(error.localizedDescription, page: number) }
            }
        }
        send(["event": "done"])
    } catch { fail(error.localizedDescription) }
}
