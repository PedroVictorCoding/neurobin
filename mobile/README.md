# Neurobin Mobile Wrapper

This directory contains the Capacitor wrapper used to ship `https://neurob.in` as native iOS and Android apps.

## 1) Install dependencies

```bash
cd mobile
npm install
```

## 2) Add native platforms

```bash
npm run add:android
npm run add:ios
```

Notes:
- iOS project generation/opening requires macOS + Xcode.
- iOS dependency sync requires CocoaPods (`pod install`).
- Android requires Android Studio + SDK.

## 3) Sync config/assets into native projects

```bash
npm run sync
```

## 4) Open native projects

```bash
npm run open:android
npm run open:ios
```

## Current behavior

- App loads `https://neurob.in` directly via Capacitor server URL.
- This gives a near 1:1 experience with the current web app.

## iOS CocoaPods fix (if needed)

If `npx cap add ios` or `npx cap sync ios` fails with `spawn pod ENOENT`, install CocoaPods:

```bash
sudo gem install cocoapods
```

Then rerun:

```bash
npm run sync
```

## Important next work before store submission

1. Add at least a few native capabilities (push notifications, native share target, deep linking).
2. Add app icons/splash screens and signing setup.
3. Validate auth/session behavior on both platforms.
4. Add offline/network error UX for first-load and reconnect scenarios.
