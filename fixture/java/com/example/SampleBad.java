package com.example;

/**
 * 故意埋雷的 Java 样本（供 parity 回归），不会被编译执行。预期命中清单见 fixture/README.md。
 */
public class SampleBad {

    private static final String DB_PASSWORD = "prod-P@ss-2026";

    // TODO: 换成连接池
    public void run(String id) {
        System.out.println("start job");
        try {
            int i = 1 / 0;
        } catch (Exception e) { }
        try {
            callRemote();
        } catch (Exception e) {
            e.printStackTrace();
        }
        String sql = "select * from t_user where id=" + id;
        String endpoint = "http://api.example.com/v1/user";
        System.err.println(sql + endpoint);
    }

    private void callRemote() {
    }
}
