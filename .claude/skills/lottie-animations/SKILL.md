# Lottie Animations in React

## Installation

```bash
npm install lottie-react
```

## Basic Usage

```jsx
import Lottie from 'lottie-react';
import animationData from './animation.json';

function MyComponent() {
  return (
    <Lottie
      animationData={animationData}
      loop={true}
      autoplay={true}
      style={{ width: 200, height: 200 }}
    />
  );
}
```

## With Ref (for playback control)

```jsx
import { useRef } from 'react';
import Lottie from 'lottie-react';
import animationData from './animation.json';

function ControlledAnimation() {
  const lottieRef = useRef(null);

  return (
    <div>
      <Lottie
        lottieRef={lottieRef}
        animationData={animationData}
        loop={false}
        autoplay={false}
      />
      <button onClick={() => lottieRef.current?.play()}>Play</button>
      <button onClick={() => lottieRef.current?.stop()}>Stop</button>
      <button onClick={() => lottieRef.current?.pause()}>Pause</button>
    </div>
  );
}
```

## Cleanup Pattern (prevent memory leaks)

```jsx
import { useRef, useEffect } from 'react';
import Lottie from 'lottie-react';
import animationData from './animation.json';

function SafeAnimation() {
  const lottieRef = useRef(null);

  useEffect(() => {
    return () => {
      // Destroy the animation instance on unmount
      lottieRef.current?.destroy();
    };
  }, []);

  return (
    <Lottie
      lottieRef={lottieRef}
      animationData={animationData}
      loop={true}
    />
  );
}
```

## Common Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `animationData` | object | required | The JSON animation data |
| `loop` | boolean | `true` | Loop the animation |
| `autoplay` | boolean | `true` | Start playing automatically |
| `style` | object | `{}` | CSS styles for the container |
| `className` | string | `''` | CSS class for the container |
| `lottieRef` | ref | - | Ref for playback control |
| `onComplete` | function | - | Called when animation finishes (non-loop) |
| `onLoopComplete` | function | - | Called after each loop iteration |
| `speed` | number | `1` | Playback speed (0.5 = half, 2 = double) |
| `segments` | [number, number] | - | Play only frames between [start, end] |

## Notes

- Animation JSON files can be created with Adobe After Effects + Bodymovin plugin, or downloaded from [LottieFiles](https://lottiefiles.com)
- Keep animation JSON files small (< 100KB) for performance
- Use `loop={false}` with `onComplete` for one-shot animations (celebrations, transitions)
- Always clean up with `destroy()` on unmount in components that mount/unmount frequently
