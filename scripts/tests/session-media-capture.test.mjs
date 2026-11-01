import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const scriptPath = fileURLToPath(
	new URL('../../crates/yosoi/src/internal/browser/page/media_capture.js', import.meta.url),
);
const mediaCaptureScript = readFileSync(scriptPath, 'utf8');

function deferred() {
	let resolve;
	let reject;
	const promise = new Promise((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}

function sourceInput(overrides = {}) {
	return {
		binding: 'nativeMediaBinding',
		property: 'nativeMediaState',
		token: 'source-token',
		include_audio: false,
		frames_per_second: 5,
		start_timeout_ms: 15_000,
		...overrides,
	};
}

function makeHarness(getDisplayMedia) {
	const timers = [];
	const notifications = [];
	const notificationWaiters = [];
	const tracks = [
		{
			stopped: false,
			listeners: new Map(),
			stop() {
				this.stopped = true;
			},
			addEventListener(name, callback) {
				this.listeners.set(name, callback);
			},
		},
	];
	const recorders = [];
	class FakeMediaStream {
		constructor(selectedTracks = tracks) {
			this.tracks = [...selectedTracks];
		}
		getVideoTracks() {
			return this.tracks.filter(track => track.kind !== 'audio');
		}
		getAudioTracks() {
			return this.tracks.filter(track => track.kind === 'audio');
		}
		getTracks() {
			return [...this.tracks];
		}
	}
	class FakeMediaRecorder {
		static isTypeSupported() {
			return true;
		}
		constructor(stream, options) {
			this.stream = stream;
			this.mimeType = options.mimeType;
			this.state = 'inactive';
			this.onstop = null;
			recorders.push(this);
		}
		start() {
			this.state = 'recording';
		}
		stop() {
			if (this.state !== 'recording') return;
			this.state = 'inactive';
			this.onstop?.();
		}
	}
	const window = {
		nativeMediaBinding(payload) {
			const message = JSON.parse(payload);
			notifications.push(message);
			for (let index = notificationWaiters.length - 1; index >= 0; index--) {
				if (notificationWaiters[index].kind === message.kind) {
					notificationWaiters[index].resolve(message);
					notificationWaiters.splice(index, 1);
				}
			}
		},
	};
	const context = vm.createContext({
		window,
		navigator: { mediaDevices: { getDisplayMedia } },
		MediaStream: FakeMediaStream,
		MediaRecorder: FakeMediaRecorder,
		setTimeout(callback, delayMs) {
			const timer = { callback, delayMs, cleared: false, fired: false };
			timers.push(timer);
			return timer;
		},
		clearTimeout(timer) {
			timer.cleared = true;
		},
		btoa(value) {
			return Buffer.from(value, 'binary').toString('base64');
		},
	});
	const run = vm.compileFunction(mediaCaptureScript, [], { parsingContext: context });
	function fireTimer(timer) {
		if (timer.cleared || timer.fired) return;
		timer.fired = true;
		timer.callback();
	}
	function waitForNotification(kind) {
		const existing = notifications.find(message => message.kind === kind);
		if (existing) return Promise.resolve(existing);
		return new Promise(resolve => notificationWaiters.push({ kind, resolve }));
	}
	return {
		run,
		window,
		timers,
		tracks,
		recorders,
		notifications,
		fireTimer,
		waitForNotification,
	};
}

test('cleanup removes the binding even before source state is installed', () => {
	const harness = makeHarness(() => {
		throw Error('cleanup must not request capture');
	});
	assert.equal(typeof harness.window.nativeMediaBinding, 'function');
	assert.equal(harness.window.nativeMediaState, undefined);
	assert.equal(
		harness.run('stop_source', {
			property: 'nativeMediaState',
			binding: 'nativeMediaBinding',
		}),
		true,
	);
	assert.equal(harness.window.nativeMediaBinding, undefined);
});

test('successful getDisplayMedia clears the permission timeout', async () => {
	const stream = {
		getVideoTracks: () => [track],
		getAudioTracks: () => [],
		getTracks: () => [track],
	};
	const track = {
		stopped: false,
		listeners: new Map(),
		stop() {
			this.stopped = true;
		},
		addEventListener(name, callback) {
			this.listeners.set(name, callback);
		},
	};
	const harness = makeHarness(() => Promise.resolve(stream));

	assert.equal(await harness.run('start_source', sourceInput()), true);
	assert.equal(harness.timers.length, 1);
	assert.equal(harness.timers[0].delayMs, 15_000);
	assert.equal(harness.timers[0].cleared, true);

	harness.fireTimer(harness.timers[0]);
	assert.equal(track.stopped, false);
	assert.ok(harness.window.nativeMediaState);
});

test('permission timeout closes state and stops tracks from a late stream', async () => {
	const permission = deferred();
	let permissionPromise;
	const harness = makeHarness(() => {
		permissionPromise = permission.promise;
		return permissionPromise;
	});
	const started = harness.run('start_source', sourceInput());

	assert.equal(harness.timers.length, 1);
	harness.fireTimer(harness.timers[0]);
	assert.equal(await started, false);
	assert.ok(harness.window.nativeMediaState);
	assert.equal(harness.run('stop_source', { property: 'nativeMediaState' }), true);
	assert.equal(harness.window.nativeMediaState, undefined);
	assert.equal(harness.window.nativeMediaBinding, undefined);

	const track = {
		stopped: false,
		listeners: new Map(),
		stop() {
			this.stopped = true;
		},
		addEventListener(name, callback) {
			this.listeners.set(name, callback);
		},
	};
	let lateResolutionObserved;
	const lateResolution = new Promise(resolve => {
		lateResolutionObserved = resolve;
	});
	permissionPromise.then(lateResolutionObserved);
	permission.resolve({
		getVideoTracks: () => [track],
		getAudioTracks: () => [],
		getTracks: () => [track],
	});
	await lateResolution;
	assert.equal(track.stopped, true);
});

test('stop_output cleans its recorder before stop_source stops the tracks', async () => {
	const track = {
		stopped: false,
		listeners: new Map(),
		stop() {
			this.stopped = true;
		},
		addEventListener(name, callback) {
			this.listeners.set(name, callback);
		},
	};
	const stream = {
		getVideoTracks: () => [track],
		getAudioTracks: () => [],
		getTracks: () => [track],
	};
	const harness = makeHarness(() => Promise.resolve(stream));
	assert.equal(await harness.run('start_source', sourceInput()), true);
	const output = harness.run('start_output', {
		property: 'nativeMediaState',
		output_id: 'output-id',
		segment: 0,
		include_audio: false,
		maximum_chunk_bytes: 1024,
	});
	assert.equal(output.mime_type, 'video/webm;codecs=vp8');
	assert.equal(harness.recorders.length, 1);
	assert.equal(harness.recorders[0].state, 'recording');

	const stopped = harness.waitForNotification('output_stopped');
	assert.equal(harness.run('stop_output', {
		property: 'nativeMediaState',
		output_id: 'output-id',
	}), true);
	await stopped;
	assert.equal(harness.recorders[0].state, 'inactive');
	assert.deepEqual(
		harness.notifications.map(event => event.kind),
		['output_stopped'],
	);
	assert.equal(track.stopped, false);

	assert.equal(harness.run('stop_source', { property: 'nativeMediaState' }), true);
	assert.equal(harness.window.nativeMediaBinding, undefined);
	assert.equal(track.stopped, true);
});
