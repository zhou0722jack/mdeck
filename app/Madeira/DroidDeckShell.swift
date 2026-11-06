import SwiftUI
import WebKit

struct DroidDeckShell: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = UIColor(red: 10 / 255, green: 11 / 255, blue: 13 / 255, alpha: 1)
        view.scrollView.isScrollEnabled = false
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.navigationDelegate = context.coordinator
        if let root = Bundle.main.url(forResource: "DroidDeckUI", withExtension: nil) {
            context.coordinator.root = root.standardizedFileURL
            view.loadFileURL(root.appendingPathComponent("index.html"), allowingReadAccessTo: root)
        }
        return view
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        var root: URL?

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url,
                  url.isFileURL, let root,
                  url.standardizedFileURL.path.hasPrefix(root.path + "/") else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
