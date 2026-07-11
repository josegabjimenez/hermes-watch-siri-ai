// swift-tools-version: 5.9
import PackageDescription

let dependencies: [Package.Dependency] = [
    .package(url: "https://github.com/apple/swift-crypto.git", from: "3.0.0"),
    // Standalone Swift toolchains on macOS may omit XCTest even when the
    // compiler is Swift 6+, so make the module an explicit dependency.
    .package(
        url: "https://github.com/swiftlang/swift-corelibs-xctest.git",
        revision: "aba63a74270b094db00c40182f8774afbe2a91e9" // swift-5.10-RELEASE
    )
]

let testDependencies: [Target.Dependency] = [
    "HermesCore",
    .product(name: "XCTest", package: "swift-corelibs-xctest")
]

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
    dependencies: dependencies,
    targets: [
        .target(
            name: "HermesCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto")
            ]
        ),
        .testTarget(
            name: "HermesCoreTests",
            dependencies: testDependencies
        )
    ]
)
