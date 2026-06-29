"""Coding domain migrations: 029, 030, 031."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_029_user_resumes(conn):
    """Create user_resumes table for persistent resume storage."""
    cursor = conn.cursor()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("PRAGMA index_list('user_resumes')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_resume_user" not in indexes:
        conn.execute("CREATE INDEX idx_resume_user ON user_resumes(user_id)")
    logger.info("已创建 user_resumes 表")


def _migration_030_coding_module(conn):
    """Create coding_problems and coding_submissions tables for the hand-tear code module."""
    cursor = conn.cursor()

    # ── coding_problems ──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS coding_problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'medium',
            tags TEXT DEFAULT '[]',
            expected_complexity TEXT DEFAULT '',
            source TEXT DEFAULT '',
            supported_languages TEXT DEFAULT '["python","c","java"]',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── coding_submissions ──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS coding_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            problem_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            code TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'full_review',
            hint_round INTEGER DEFAULT 0,
            parent_submission_id INTEGER,
            ai_feedback TEXT DEFAULT '',
            error_categories TEXT DEFAULT '[]',
            is_passed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (problem_id) REFERENCES coding_problems(id),
            FOREIGN KEY (parent_submission_id) REFERENCES coding_submissions(id)
        )
    ''')

    # Indexes
    cursor.execute("PRAGMA index_list('coding_submissions')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_coding_sub_user" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_user ON coding_submissions(user_id)")
    if "idx_coding_sub_problem" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_problem ON coding_submissions(problem_id)")
    if "idx_coding_sub_parent" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_parent ON coding_submissions(parent_submission_id)")

    # ── Seed 50 high-frequency interview coding problems ──
    problems = [
        # 数组/字符串
        ("两数之和", "给定一个整数数组 `nums` 和一个整数目标值 `target`，请你在该数组中找出和为目标值的两个整数，并返回它们的数组下标。\n\n**示例：**\n```\n输入：nums = [2,7,11,15], target = 9\n输出：[0,1]\n解释：因为 nums[0] + nums[1] == 9\n```", "easy", '["数组","哈希表"]', "O(n)", "LeetCode #1"),
        ("三数之和", "给你一个整数数组 `nums`，判断是否存在三元组 `[nums[i], nums[j], nums[k]]` 满足 `i != j != k` 且 `nums[i] + nums[j] + nums[k] == 0`。返回所有和为 0 的三元组。\n\n**示例：**\n```\n输入：nums = [-1,0,1,2,-1,-4]\n输出：[[-1,-1,2],[-1,0,1]]\n```", "medium", '["数组","双指针","排序"]', "O(n²)", "LeetCode #15"),
        ("盛最多水的容器", "给定一个长度为 n 的整数数组 `height`，其中 `height[i]` 表示第 i 条线的高度。找出其中的两条线，使得它们与 x 轴共同构成的容器可以容纳最多的水。返回最大面积。\n\n**示例：**\n```\n输入：height = [1,8,6,2,5,4,8,3,7]\n输出：49\n```", "medium", '["数组","双指针"]', "O(n)", "LeetCode #11"),
        ("无重复字符的最长子串", "给定一个字符串 `s`，请你找出其中不含有重复字符的最长子串的长度。\n\n**示例：**\n```\n输入：s = \"abcabcbb\"\n输出：3\n解释：最长子串为 \"abc\"\n```", "medium", '["字符串","滑动窗口"]', "O(n)", "LeetCode #3"),
        ("最长回文子串", "给你一个字符串 `s`，找到 `s` 中最长的回文子串。\n\n**示例：**\n```\n输入：s = \"babad\"\n输出：\"bab\" 或 \"aba\"\n```", "medium", '["字符串","动态规划"]', "O(n²)", "LeetCode #5"),
        ("合并两个有序数组", "给你两个按非递减顺序排列的整数数组 `nums1` 和 `nums2`，以及两个整数 `m` 和 `n`，分别表示 `nums1` 和 `nums2` 中的元素数量。将 `nums2` 合并到 `nums1` 中，使合并后的数组按非递减顺序排列。\n\n**示例：**\n```\n输入：nums1 = [1,2,3,0,0,0], m = 3, nums2 = [2,5,6], n = 3\n输出：[1,2,2,3,5,6]\n```", "easy", '["数组","双指针"]', "O(m+n)", "LeetCode #88"),
        ("寻找两个正序数组的中位数", "给定两个大小分别为 m 和 n 的正序数组 `nums1` 和 `nums2`，请你找出并返回这两个正序数组的中位数。算法的时间复杂度应该为 O(log(m+n))。\n\n**示例：**\n```\n输入：nums1 = [1,3], nums2 = [2]\n输出：2.0\n```", "hard", '["数组","二分查找"]', "O(log(m+n))", "LeetCode #4"),
        ("接雨水", "给定 n 个非负整数表示每个宽度为 1 的柱子的高度图，计算按此排列的柱子，下雨之后能接多少雨水。\n\n**示例：**\n```\n输入：height = [0,1,0,2,1,0,1,3,2,1,2,1]\n输出：6\n```", "hard", '["数组","双指针","栈"]', "O(n)", "LeetCode #42"),
        # 链表
        ("反转链表", "给你单链表的头节点 `head`，请你反转链表，并返回反转后的链表。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5]\n输出：[5,4,3,2,1]\n```", "easy", '["链表"]', "O(n)", "LeetCode #206"),
        ("合并两个有序链表", "将两个升序链表合并为一个新的升序链表并返回。新链表是通过拼接给定的两个链表的所有节点组成的。\n\n**示例：**\n```\n输入：l1 = [1,2,4], l2 = [1,3,4]\n输出：[1,1,2,3,4,4]\n```", "easy", '["链表"]', "O(n+m)", "LeetCode #21"),
        ("环形链表", "给你一个链表的头节点 `head`，判断链表中是否有环。如果链表中存在环，则返回 true；否则返回 false。\n\n**示例：**\n```\n输入：head = [3,2,0,-4]（pos = 1，表示尾部连接到第二个节点）\n输出：true\n```", "easy", '["链表","双指针"]', "O(n)", "LeetCode #141"),
        ("相交链表", "给你两个单链表的头节点 `headA` 和 `headB`，请你找出并返回两个单链表相交的起始节点。如果不存在则返回 null。\n\n**示例：**\n```\n输入：intersectVal = 8, listA = [4,1,8,4,5], listB = [5,6,1,8,4,5]\n输出：节点值为 8 的节点\n```", "easy", '["链表","双指针"]', "O(m+n)", "LeetCode #160"),
        ("删除链表的倒数第 N 个结点", "给你一个链表，删除链表的倒数第 n 个结点，并且返回链表的头结点。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5], n = 2\n输出：[1,2,3,5]\n```", "medium", '["链表","双指针"]', "O(L)", "LeetCode #19"),
        ("K 个一组翻转链表", "给你一个链表，每 k 个节点一组进行翻转，请你返回修改后的链表。如果节点总数不是 k 的整数倍，则最后剩余的节点保持原有顺序。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5], k = 2\n输出：[2,1,4,3,5]\n```", "hard", '["链表","递归"]', "O(n)", "LeetCode #25"),
        # 树
        ("二叉树的中序遍历", "给定一个二叉树的根节点 `root`，返回它的中序遍历结果。\n\n**示例：**\n```\n输入：root = [1,null,2,3]\n输出：[1,3,2]\n```", "easy", '["树","栈","递归"]', "O(n)", "LeetCode #94"),
        ("二叉树的最大深度", "给定一个二叉树 `root`，返回其最大深度。最大深度是从根节点到最远叶子节点的最长路径上的节点数。\n\n**示例：**\n```\n输入：root = [3,9,20,null,null,15,7]\n输出：3\n```", "easy", '["树","DFS","BFS"]', "O(n)", "LeetCode #104"),
        ("翻转二叉树", "给你一棵二叉树的根节点 `root`，翻转这棵二叉树，并返回其根节点。\n\n**示例：**\n```\n输入：root = [4,2,7,1,3,6,9]\n输出：[4,7,2,9,6,3,1]\n```", "easy", '["树","递归"]', "O(n)", "LeetCode #226"),
        ("验证二叉搜索树", "给你一个二叉树的根节点 `root`，判断其是否是一个有效的二叉搜索树（BST）。\n\n**示例：**\n```\n输入：root = [2,1,3]\n输出：true\n```", "medium", '["树","BST","递归"]', "O(n)", "LeetCode #98"),
        ("二叉树的层序遍历", "给你二叉树的根节点 `root`，返回其节点值的层序遍历（逐层，从左到右）。\n\n**示例：**\n```\n输入：root = [3,9,20,null,null,15,7]\n输出：[[3],[9,20],[15,7]]\n```", "medium", '["树","BFS"]', "O(n)", "LeetCode #102"),
        ("从前序与中序遍历序列构造二叉树", "给定两个整数数组 `preorder` 和 `inorder`，其中 `preorder` 是二叉树的前序遍历，`inorder` 是同一棵树的中序遍历，请构造二叉树并返回其根节点。\n\n**示例：**\n```\n输入：preorder = [3,9,20,15,7], inorder = [9,3,15,20,7]\n输出：[3,9,20,null,null,15,7]\n```", "medium", '["树","递归","分治"]', "O(n)", "LeetCode #105"),
        ("二叉树的最近公共祖先", "给定一个二叉树, 找到该树中两个指定节点的最近公共祖先（LCA）。\n\n**示例：**\n```\n输入：root = [3,5,1,6,2,0,8,null,null,7,4], p = 5, q = 1\n输出：3\n```", "medium", '["树","递归"]', "O(n)", "LeetCode #236"),
        ("二叉树中的最大路径和", "给你一个二叉树的根节点 `root`，返回其最大路径和。路径被定义为一条从树中任意节点出发，沿父节点-子节点连接，达到任意节点的序列。\n\n**示例：**\n```\n输入：root = [-10,9,20,null,null,15,7]\n输出：42（15→20→7）\n```", "hard", '["树","DFS","递归"]', "O(n)", "LeetCode #124"),
        # 排序与搜索
        ("快速排序", "实现快速排序算法。给定一个整数数组 `nums`，将数组升序排列。\n\n**要求：**\n- 实现 `partition` 过程\n- 平均时间复杂度 O(nlogn)\n\n**示例：**\n```\n输入：nums = [5,2,3,1]\n输出：[1,2,3,5]\n```", "medium", '["排序","分治"]', "O(nlogn)", "经典算法"),
        ("归并排序", "实现归并排序算法。给定一个整数数组 `nums`，将数组升序排列。\n\n**要求：**\n- 实现分治+合并过程\n- 时间复杂度稳定 O(nlogn)\n\n**示例：**\n```\n输入：nums = [5,2,3,1]\n输出：[1,2,3,5]\n```", "medium", '["排序","分治"]', "O(nlogn)", "经典算法"),
        ("二分查找", "给定一个升序排列的整数数组 `nums` 和一个目标值 `target`。如果目标值存在于数组中，返回其下标，否则返回 -1。\n\n**示例：**\n```\n输入：nums = [-1,0,3,5,9,12], target = 9\n输出：4\n```", "easy", '["数组","二分查找"]', "O(logn)", "LeetCode #704"),
        ("搜索旋转排序数组", "整数数组 `nums` 按升序排列，数组中的值互不相同。在传递给函数之前，`nums` 在预先未知的某个下标上进行了旋转。给你旋转后的数组 `nums` 和一个整数 `target`，如果 `nums` 中存在这个目标值，则返回它的下标，否则返回 -1。\n\n**示例：**\n```\n输入：nums = [4,5,6,7,0,1,2], target = 0\n输出：4\n```", "medium", '["数组","二分查找"]', "O(logn)", "LeetCode #33"),
        ("在排序数组中查找元素的第一个和最后一个位置", "给你一个按非递减顺序排列的整数数组 `nums`，和一个目标值 `target`。请你找出给定目标值在数组中的开始位置和结束位置。如果不存在则返回 [-1, -1]。\n\n**示例：**\n```\n输入：nums = [5,7,7,8,8,10], target = 8\n输出：[3,4]\n```", "medium", '["数组","二分查找"]', "O(logn)", "LeetCode #34"),
        # 动态规划
        ("爬楼梯", "假设你正在爬楼梯。需要 n 阶你才能到达楼顶。每次你可以爬 1 或 2 个台阶。你有多少种不同的方法可以爬到楼顶？\n\n**示例：**\n```\n输入：n = 3\n输出：3\n解释：1+1+1, 1+2, 2+1\n```", "easy", '["动态规划"]', "O(n)", "LeetCode #70"),
        ("最大子数组和", "给你一个整数数组 `nums`，请你找出一个具有最大和的连续子数组（子数组最少包含一个元素），返回其最大和。\n\n**示例：**\n```\n输入：nums = [-2,1,-3,4,-1,2,1,-5,4]\n输出：6\n解释：连续子数组 [4,-1,2,1] 的和最大\n```", "medium", '["动态规划","分治"]', "O(n)", "LeetCode #53"),
        ("零钱兑换", "给你一个整数数组 `coins` 表示不同面额的硬币和一个整数 `amount` 表示总金额。计算并返回可以凑成总金额所需的最少硬币个数。如果无法凑成，返回 -1。\n\n**示例：**\n```\n输入：coins = [1,2,5], amount = 11\n输出：3\n解释：11 = 5 + 5 + 1\n```", "medium", '["动态规划","BFS"]', "O(n*amount)", "LeetCode #322"),
        ("最长递增子序列", "给你一个整数数组 `nums`，找到其中最长严格递增子序列的长度。\n\n**示例：**\n```\n输入：nums = [10,9,2,5,3,7,101,18]\n输出：4\n解释：最长递增子序列为 [2,3,7,101]\n```", "medium", '["动态规划","二分查找"]', "O(nlogn)", "LeetCode #300"),
        ("编辑距离", "给你两个单词 `word1` 和 `word2`，请返回将 `word1` 转换成 `word2` 所使用的最少操作数。你可以进行插入、删除、替换一个字符的操作。\n\n**示例：**\n```\n输入：word1 = \"horse\", word2 = \"ros\"\n输出：3\n```", "hard", '["动态规划","字符串"]', "O(mn)", "LeetCode #72"),
        ("最长公共子序列", "给定两个字符串 `text1` 和 `text2`，返回这两个字符串的最长公共子序列的长度。\n\n**示例：**\n```\n输入：text1 = \"abcde\", text2 = \"ace\"\n输出：3\n解释：最长公共子序列是 \"ace\"\n```", "medium", '["动态规划","字符串"]', "O(mn)", "LeetCode #1143"),
        ("不同路径", "一个机器人位于 `m x n` 网格的左上角，每次只能向下或向右移动一步。机器人试图达到网格的右下角。问总共有多少条不同的路径？\n\n**示例：**\n```\n输入：m = 3, n = 7\n输出：28\n```", "medium", '["动态规划","数学"]', "O(mn)", "LeetCode #62"),
        ("最小路径和", "给定一个包含非负整数的 `m x n` 网格 `grid`，请找出一条从左上角到右下角的路径，使得路径上的数字总和为最小。每次只能向下或者向右移动一步。\n\n**示例：**\n```\n输入：grid = [[1,3,1],[1,5,1],[4,2,1]]\n输出：7\n解释：路径 1→3→1→1→1 的总和最小\n```", "medium", '["动态规划","矩阵"]', "O(mn)", "LeetCode #64"),
        # 栈/队列
        ("有效的括号", "给定一个只包括 `(`，`)`，`{`，`}`，`[`，`]` 的字符串 `s`，判断字符串是否有效。有效字符串需满足：左括号必须用相同类型的右括号闭合，按正确顺序闭合。\n\n**示例：**\n```\n输入：s = \"()[]{}\"\n输出：true\n```", "easy", '["栈","字符串"]', "O(n)", "LeetCode #20"),
        ("最小栈", "设计一个支持 `push`、`pop`、`top` 操作，并能在常数时间内检索到最小元素的栈。\n\n**示例：**\n```\nMinStack minStack = new MinStack();\nminStack.push(-2);\nminStack.push(0);\nminStack.push(-3);\nminStack.getMin(); // 返回 -3\nminStack.pop();\nminStack.top();    // 返回 0\nminStack.getMin(); // 返回 -2\n```", "easy", '["栈","设计"]', "O(1)", "LeetCode #155"),
        ("用栈实现队列", "使用两个栈实现先入先出队列。队列应当支持一般队列支持的所有操作（push、pop、peek、empty）。\n\n**示例：**\n```\nMyQueue queue = new MyQueue();\nqueue.push(1);\nqueue.push(2);\nqueue.peek();  // 返回 1\nqueue.pop();   // 返回 1\nqueue.empty(); // 返回 false\n```", "easy", '["栈","队列","设计"]', "均摊 O(1)", "LeetCode #232"),
        ("每日温度", "给定一个整数数组 `temperatures` 表示每天的温度，返回一个数组 `answer`，其中 `answer[i]` 表示第 i 天之后需要等几天才能等到更暖和的气温。如果之后都不会更暖和，则 `answer[i] = 0`。\n\n**示例：**\n```\n输入：temperatures = [73,74,75,71,69,72,76,73]\n输出：[1,1,4,2,1,1,0,0]\n```", "medium", '["栈","单调栈"]', "O(n)", "LeetCode #739"),
        # 字符串
        ("反转字符串", "编写一个函数，将输入的字符串反转过来。\n\n**示例：**\n```\n输入：[\"h\",\"e\",\"l\",\"l\",\"o\"]\n输出：[\"o\",\"l\",\"l\",\"e\",\"h\"]\n```", "easy", '["字符串","双指针"]', "O(n)", "LeetCode #344"),
        ("字符串转换整数 (atoi)", "实现 `myAtoi(string s)` 函数，将字符串转换成一个 32 位有符号整数。\n\n**示例：**\n```\n输入：s = \"42\"\n输出：42\n\n输入：s = \"   -42\"\n输出：-42\n```", "medium", '["字符串","有限状态机"]', "O(n)", "LeetCode #8"),
        # 回溯
        ("全排列", "给定一个不含重复数字的数组 `nums`，返回其所有可能的全排列。\n\n**示例：**\n```\n输入：nums = [1,2,3]\n输出：[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]]\n```", "medium", '["回溯","递归"]', "O(n!×n)", "LeetCode #46"),
        ("子集", "给你一个整数数组 `nums`，数组中的元素互不相同。返回该数组所有可能的子集。\n\n**示例：**\n```\n输入：nums = [1,2,3]\n输出：[[],[1],[2],[1,2],[3],[1,3],[2,3],[1,2,3]]\n```", "medium", '["回溯","位运算"]', "O(n×2ⁿ)", "LeetCode #78"),
        ("电话号码的字母组合", "给定一个仅包含数字 2-9 的字符串，返回所有它能表示的字母组合。数字到字母的映射与电话按键相同。\n\n**示例：**\n```\n输入：digits = \"23\"\n输出：[\"ad\",\"ae\",\"af\",\"bd\",\"be\",\"bf\",\"cd\",\"ce\",\"cf\"]\n```", "medium", '["回溯","字符串"]', "O(4ⁿ×n)", "LeetCode #17"),
        ("括号生成", "数字 n 代表生成括号的对数，请你设计一个函数，用于能够生成所有可能的并且有效的括号组合。\n\n**示例：**\n```\n输入：n = 3\n输出：[\"((()))\",\"(()())\",\"(())()\",\"()(())\",\"()()()\"]\n```", "medium", '["回溯","递归"]', "O(4ⁿ/√n)", "LeetCode #22"),
        # 图
        ("岛屿数量", "给你一个由 `'1'`（陆地）和 `'0'`（水）组成的二维网格，请你计算网格中岛屿的数量。\n\n**示例：**\n```\n输入：grid = [\n  [\"1\",\"1\",\"0\",\"0\",\"0\"],\n  [\"1\",\"1\",\"0\",\"0\",\"0\"],\n  [\"0\",\"0\",\"1\",\"0\",\"0\"],\n  [\"0\",\"0\",\"0\",\"1\",\"1\"]\n]\n输出：3\n```", "medium", '["图","DFS","BFS"]', "O(mn)", "LeetCode #200"),
        ("课程表", "你这个学期必须选修 `numCourses` 门课程，记为 0 到 numCourses-1。在选修某些课程之前需要一些先修课程。判断是否可能完成所有课程的学习？\n\n**示例：**\n```\n输入：numCourses = 2, prerequisites = [[1,0]]\n输出：true\n解释：先修课程 0，再修课程 1\n```", "medium", '["图","拓扑排序","BFS"]', "O(V+E)", "LeetCode #207"),
        # 堆
        ("前 K 个高频元素", "给你一个整数数组 `nums` 和一个整数 `k`，请你返回其中出现频率前 k 高的元素。可以按任意顺序返回答案。\n\n**示例：**\n```\n输入：nums = [1,1,1,2,2,3], k = 2\n输出：[1,2]\n```", "medium", '["堆","哈希表","排序"]', "O(nlogk)", "LeetCode #347"),
        ("数据流的中位数", "中位数是有序整数列表中间的数。设计一个支持以下两种操作的数据结构：`addNum(num)` 从数据流中添加一个整数到数据结构中；`findMedian()` 返回目前所有元素的中位数。\n\n**示例：**\n```\naddNum(1)\naddNum(2)\nfindMedian() -> 1.5\naddNum(3)\nfindMedian() -> 2\n```", "hard", '["堆","设计"]', "O(logn)", "LeetCode #295"),
        ("合并区间", "以数组 `intervals` 表示若干个区间的集合，其中单个区间为 `intervals[i] = [starti, endi]`。请你合并所有重叠的区间，并返回一个不重叠的区间数组。\n\n**示例：**\n```\n输入：intervals = [[1,3],[2,6],[8,10],[15,18]]\n输出：[[1,6],[8,10],[15,18]]\n解释：区间 [1,3] 和 [2,6] 重叠，合并为 [1,6]\n```", "medium", '["数组","排序"]', "O(nlogn)", "LeetCode #56"),
    ]

    for title, desc, diff, tags, complexity, source in problems:
        cursor.execute("SELECT id FROM coding_problems WHERE title = ?", (title,))
        if not cursor.fetchone():
            conn.execute(
                "INSERT INTO coding_problems (title, description, difficulty, tags, expected_complexity, source) VALUES (?, ?, ?, ?, ?, ?)",
                (title, desc, diff, tags, complexity, source)
            )

    logger.info("已创建 coding_problems / coding_submissions 表，插入 50 道初始题目")


def _migration_031_coding_scores(conn):
    """Add scores, reference_answer, total_score columns to coding_submissions."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(coding_submissions)")
    columns = {row[1] for row in cursor.fetchall()}

    if "scores" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN scores TEXT DEFAULT '{}'")
    if "reference_answer" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN reference_answer TEXT DEFAULT ''")
    if "total_score" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN total_score REAL DEFAULT 0")

    logger.info("已为 coding_submissions 添加 scores/reference_answer/total_score 列")
