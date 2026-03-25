# Bridge API

这份文档是 `STS2CLI` 当前实际依赖的本地接口摘要。

基地址：

```text
http://localhost:15526/api/v1/singleplayer
```

## 读取状态

请求：

```http
GET /api/v1/singleplayer?format=json
```

主要 `state_type`：

- `monster` / `elite` / `boss`：战斗中
- `hand_select`：战斗中卡牌选择
- `combat_rewards`：战后奖励
- `card_reward`：选卡奖励
- `map`：地图选点
- `rest_site`：休息点
- `shop`：商店
- `event`：事件或远古事件
- `card_select`：卡牌选择覆盖层
- `relic_select`：遗物选择
- `treasure`：宝箱房
- `overlay`：未适配覆盖层
- `menu`：当前没有 run

## 发送动作

请求：

```http
POST /api/v1/singleplayer
Content-Type: application/json
```

### 战斗

出牌：

```json
{"action":"play_card","card_index":0,"target":"jaw_worm_0"}
```

用药水：

```json
{"action":"use_potion","slot":0,"target":"jaw_worm_0"}
```

结束回合：

```json
{"action":"end_turn"}
```

战斗中选卡：

```json
{"action":"combat_select_card","card_index":0}
```

确认战斗中选卡：

```json
{"action":"combat_confirm_selection"}
```

### 奖励

领取奖励：

```json
{"action":"claim_reward","index":0}
```

选择卡牌奖励：

```json
{"action":"select_card_reward","card_index":0}
```

跳过卡牌奖励：

```json
{"action":"skip_card_reward"}
```

### 地图与房间

地图选点：

```json
{"action":"choose_map_node","index":0}
```

休息点：

```json
{"action":"choose_rest_option","index":0}
```

商店购买：

```json
{"action":"shop_purchase","index":0}
```

事件选项：

```json
{"action":"choose_event_option","index":0}
```

推进远古事件对话：

```json
{"action":"advance_dialogue"}
```

通用继续：

```json
{"action":"proceed"}
```

### 覆盖层

卡牌选择：

```json
{"action":"select_card","index":0}
```

确认选择：

```json
{"action":"confirm_selection"}
```

取消选择：

```json
{"action":"cancel_selection"}
```

选择遗物：

```json
{"action":"select_relic","index":0}
```

跳过遗物选择：

```json
{"action":"skip_relic_selection"}
```

领取宝箱遗物：

```json
{"action":"claim_treasure_relic","index":0}
```

## 注意

- 这个接口是本地接口，不应该暴露到公网
- 当前 `STS2CLI` 只使用单人接口
- 当前没有主菜单自动开局接口，所以需要先手动开一局
