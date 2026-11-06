import SwiftUI

@main
struct MadeiraApp: App {
    var body: some Scene {
        WindowGroup {
            DroidDeckShell()
                .ignoresSafeArea()
                .preferredColorScheme(.dark)
                .statusBarHidden(true)
                .persistentSystemOverlays(.hidden)
        }
    }
}
