package com.example;

import java.util.logging.Logger;

/**
 * 干净样本：不应产生任何发现。
 */
public class SampleGood {

    private static final Logger LOG = Logger.getLogger(SampleGood.class.getName());

    public String findUser(String id) {
        LOG.info("find user " + id);
        // 参数化查询，不拼接
        String sql = "select * from t_user where id = ?";
        return sql + id.length();
    }
}
