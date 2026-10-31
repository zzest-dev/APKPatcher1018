package com.bigcitylegacy.backend;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.Toast;
import com.unity3d.player.UnityPlayer;
import com.unity3d.player.UnityPlayerActivity;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.util.Properties;

public final class BackendActivity extends UnityPlayerActivity {
    private static native int nativeInitialize(String ip, int port);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String ip;
    private int port;
    private int attempts;
    private boolean destroyed;
    private Method queue;

    private final Runnable initialize = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            try {
                if (queue == null) {
                    queue = UnityPlayer.class.getDeclaredMethod("queueGLThreadEvent", Runnable.class);
                    queue.setAccessible(true);
                }
                queue.invoke(mUnityPlayer, new Runnable() {
                    @Override public void run() {
                        final int result = nativeInitialize(ip, port);
                        handler.post(new Runnable() {
                            @Override public void run() {
                                if (destroyed) return;
                                if (result == 1) {
                                    Log.i("Backend1018", "Endpoint active: " + ip + ":" + port);
                                    Toast.makeText(BackendActivity.this, "Backend: " + ip + ":" + port, Toast.LENGTH_LONG).show();
                                } else if (result == 0 && ++attempts < 240) {
                                    handler.postDelayed(initialize, 250);
                                } else {
                                    fail("Backend hook initialization failed: " + result);
                                }
                            }
                        });
                    }
                });
            } catch (Throwable error) {
                fail("Unity queue unavailable: " + error.getClass().getSimpleName());
            }
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            File directory = getExternalFilesDir(null);
            if (directory == null) throw new IllegalStateException("External data unavailable");
            File config = new File(directory, "backend.txt");
            if (!config.exists()) {
                try (InputStream input = getAssets().open("backend-defaults.properties"); FileOutputStream output = new FileOutputStream(config)) {
                    byte[] buffer = new byte[1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                }
            }
            if (config.length() > 4096) throw new IllegalArgumentException("backend.txt exceeds 4096 bytes");
            Properties properties = new Properties();
            try (FileInputStream input = new FileInputStream(config)) { properties.load(input); }
            ip = properties.getProperty("ip", "").trim();
            port = Integer.parseInt(properties.getProperty("port", "").trim());
            String[] octets = ip.split("\\.", -1);
            if (octets.length != 4 || port < 1 || port > 65535) throw new IllegalArgumentException("Use IPv4 and port 1..65535");
            for (String octet : octets) {
                if (!octet.matches("[0-9]{1,3}") || Integer.parseInt(octet) > 255) throw new IllegalArgumentException("Invalid IPv4");
            }
            Log.i("Backend1018", "Config: " + config.getAbsolutePath() + " -> " + ip + ":" + port);
            System.loadLibrary("backend1018");
            handler.postDelayed(initialize, 1000);
        } catch (Throwable error) {
            fail("backend.txt: " + error.getMessage());
        }
    }

    private void fail(String message) {
        Log.e("Backend1018", message);
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        finish();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
