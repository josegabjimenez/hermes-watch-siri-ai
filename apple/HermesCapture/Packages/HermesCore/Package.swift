// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HermesCore",
    platforms: [
        .iOS(.v17),
        .watchOS(.v10),
        .macOS(.v13)
    ],
    products: [
        .library(name: "HermesCore", targets: ["HermesCore"])
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-crypto.git", from: "3.0.0")
    ],
    targets: [
        .target(
            name: "HermesCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto")
            ]
        ),
        .testTarget(
            name: "HermesCoreTests",
            dependencies: ["HermesCore"]
        )
    ]
)
